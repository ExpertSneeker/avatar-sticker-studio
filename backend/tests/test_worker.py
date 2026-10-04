import asyncio
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.worker import Worker
from backend.tests.helpers import png, template, order, customer_action, order_items, stored_order, slot_for, submit_and_publish, run_all


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value


class Provider:
    def __init__(self): self.calls = []; self.error = None
    async def generate(self, template, avatar, prompt):
        self.calls.append((template, avatar, prompt))
        if self.error: raise self.error
        return png(size=(1024, 1024))


@pytest.fixture
def context(tmp_path):
    clock, provider = Clock(), Provider()
    app = create_app(tmp_path, provider=provider, clock=clock, start_worker=False)
    with TestClient(app) as client:
        client.post('/api/auth/setup', json={'username': 'admin', 'password': 'safe-password-123', 'display_name': '管理员'})
        yield app, client, clock, provider


def test_global_claim_pause_rate_and_restart_unknown(context):
    app, client, clock, provider = context
    o, _ = order(client)
    a = app.state.worker
    b = Worker(app.state.db, provider=provider, clock=clock)
    assert hasattr(a, 'claim'), 'durable transactional claims missing'
    first, second = a.claim(), b.claim()
    assert first and second and first['id'] != second['id']
    assert a.claim() is None
    customer_action(client,o,'cancel')
    asyncio.run(a.execute(first)); asyncio.run(b.execute(second))
    assert a.claim() is None
    customer_action(client,o,'restore')
    for _ in range(3): asyncio.run(a.execute(a.claim()))
    clock.value += 61
    abandoned = a.claim()
    assert abandoned
    clock.value += 61
    b.recover()
    result = client.get('/api/customer-orders/' + o['id']).json()
    assert sum(i['status']=='unknown' for i in order_items(app,o)) == 1
    assert next(i for i in order_items(app,o) if i['id']==abandoned['id'])['status']=='unknown'


def test_complete_two_sets_repack_watermark_rerun_and_manifest(context):
    app,client,clock,provider=context
    t1,t2=template(client,'A01'),template(client,'B02')
    o,_=order(client,template_ids=[t2['id'],t1['id']])
    listed=client.get('/api/customer-orders').json()[0]
    assert listed['preview_url'] is None and not listed['delivery_ready']
    run_all(app)
    assert len(provider.calls)==24
    before=client.get('/api/customer-orders/'+o['id']).json()
    slot=before['slots'][0]; original=slot['selected_version_id']
    assert customer_action(client,o,'slots/'+slot['id']+'/rerun').status_code==200
    run_all(app)
    current=client.get('/api/customer-orders/'+o['id']).json()
    changed=current['slots'][0]
    assert changed['selected_version_id']==original and changed['pending_version_id']!=original
    assert customer_action(client,o,'slots/'+slot['id']+'/select',version_id=changed['pending_version_id']).status_code==200
    result=submit_and_publish(app,client,o)
    assert result['delivery_ready'] and result['preview_url']
    manifest=client.get('/api/customer-orders/'+o['id']+'/manifest').json()
    assert len(manifest['files'])==4 and all(f['kind']=='print' for f in manifest['files'])
    assert Image.open(io.BytesIO(client.get('/api/assets/'+stored_order(app,o)['overview_id']).content)).size==(1024,1536)
    count=len(provider.calls)
    assert customer_action(client,o,'repack',print_settings={'long_edge_mm':50}).status_code==200
    assert app.state.worker.publish(o['id'])
    pages=client.get('/api/customer-orders/'+o['id']+'/manifest').json()['files']
    assert len(pages)==2
    client.patch('/api/account',json={'watermark':'仅供预览'})
    preview=client.post('/api/customer-orders/watermarks/preview',json={'ids':[o['id']]}).json()
    assert client.post('/api/customer-orders/watermarks',json={'ids':[o['id']],'preview_token':preview['preview_token'],'client_token':'marks'}).status_code==200
    assert app.state.worker.publish(o['id'])
    assert client.get('/api/customer-orders/'+o['id']+'/manifest').json()['files']==pages
    assert len(provider.calls)==count
    assert client.get('/api/customer-orders/'+o['id']+'/download.zip').status_code==200

def test_unknown_refused_and_retry_are_distinct(context):
    app, client, clock, provider = context
    worker = app.state.worker
    assert hasattr(worker, 'claim'), 'durable worker missing'
    from backend.app.providers import ProviderFailure
    o, _ = order(client)
    provider.error = ProviderFailure('结果待确认', 'unknown')
    asyncio.run(worker.execute(worker.claim()))
    assert sum(i['status']=='unknown' for i in order_items(app,o)) == 1
    provider.error = ProviderFailure('内容拒绝', 'failed')
    asyncio.run(worker.execute(worker.claim()))
    assert sum(i['status']=='failed' for i in order_items(app,o)) == 1
    provider.error = ProviderFailure('频率受限', 'retry', 30)
    item = worker.claim()
    asyncio.run(worker.execute(item))
    with app.state.db.transaction() as tx:
        value = tx.get('items', item['id'])
    assert value['status'] == 'queued'
    assert value['next_at'] == clock.value + 30
    assert value['attempt'] == 1


def test_unexpected_provider_transport_failure_is_unknown(context):
    app, client, clock, provider = context
    o, _ = order(client)
    provider.error = RuntimeError('connection vanished')
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    assert sum(i['status']=='unknown' for i in order_items(app,o)) == 1


def test_racing_workers_do_not_exceed_global_inflight(context):
    from concurrent.futures import ThreadPoolExecutor
    app, client, clock, provider = context
    order(client)
    workers = [Worker(app.state.db, provider=provider, clock=clock) for _ in range(8)]
    with ThreadPoolExecutor(8) as pool:
        claims = list(pool.map(lambda worker: worker.claim(), workers))
    assert len([c for c in claims if c]) == 2
    assert len({c['id'] for c in claims if c}) == 2


def test_repack_marks_durable_pending_before_image_processing(context, monkeypatch):
    app,client,_,_=context
    o,_=order(client);run_all(app);submit_and_publish(app,client,o)
    assert customer_action(client,o,'repack',print_settings={'long_edge_mm':50}).status_code==200
    saved=stored_order(app,o)
    assert saved['delivery_ready'] is False and saved['print_settings']['long_edge_mm']==50
    assert o['id'] in app.state.worker.unpublished()

def test_failed_rerun_retains_previous_result_and_delivery_version(context):
    from backend.app.providers import ProviderFailure
    app,client,_,provider=context
    o,_=order(client);run_all(app)
    before=client.get('/api/customer-orders/'+o['id']).json()
    slot=before['slots'][0]
    original=order_items(app,o)[0]
    assert customer_action(client,o,'slots/'+slot['id']+'/rerun').status_code==200
    provider.error=ProviderFailure('内容被拒绝','failed');run_all(app)
    after=client.get('/api/customer-orders/'+o['id']).json()
    assert after['slots'][0]['status']=='failed'
    assert after['slots'][0]['selected_version_id']==slot['selected_version_id']
    assert after['slots'][0]['versions']==slot['versions']
    assert after['delivery_version']==before['delivery_version']
    assert order_items(app,o)[0]['result_id']==original['result_id']

def test_background_lifecycle_publishes_and_shutdown_releases_worker(tmp_path):
    import time
    provider=Provider();app=create_app(tmp_path,provider=provider,start_worker=True)
    with TestClient(app) as client:
        client.post('/api/auth/setup',json={'username':'admin','password':'safe-password-123','display_name':'管理员'})
        client.patch('/api/admin/settings',json={'max_inflight':16})
        o,_=order(client);deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            result=client.get('/api/customer-orders/'+o['id']).json()
            if all(s['selected_version_id'] for s in result['slots']):break
            time.sleep(.1)
        assert all(s['selected_version_id'] for s in result['slots']),result
        assert customer_action(client,o,'submit',slot_ids=[s['id'] for s in result['slots']]).status_code==200
        while time.monotonic()<deadline:
            result=client.get('/api/customer-orders/'+o['id']).json()
            if result['delivery_ready']:break
            time.sleep(.1)
        assert result['delivery_ready'] and len(provider.calls)==12
    with app.state.db.transaction() as tx:assert not tx.all('workers')

def test_reprocess_recovers_paid_raw_after_restart_without_openai(context, monkeypatch):
    from backend.app.providers import YeziProvider,ProviderFailure
    app,client,clock,provider=context
    async def opaque(**kwargs):
        provider.calls.append(kwargs)
        output=io.BytesIO();Image.new('RGB',(1024,1024),'red').save(output,'PNG');return output.getvalue()
    monkeypatch.setattr(provider,'generate',opaque)
    o,_=order(client);item=app.state.worker.claim();asyncio.run(app.state.worker.execute(item))
    first=order_items(app,o)[0]
    assert first['status']=='failed' and first['raw_result_id'] and len(provider.calls)==1
    assert customer_action(client,o,'cancel').status_code==200
    restarted_provider=Provider();restarted=create_app(app.state.db.root,provider=restarted_provider,clock=clock,start_worker=False)
    async def cutout(self,data):
        assert Image.open(io.BytesIO(data)).getpixel((10,10))==(255,0,0,255)
        return png(size=(1024,1024))
    monkeypatch.setattr(YeziProvider,'cutout',cutout)
    with TestClient(restarted) as restored:
        restored.post('/api/auth/login',json={'username':'admin','password':'safe-password-123'})
        restored.patch('/api/admin/settings',json={'cutout_api_key':'test-cutout-key'})
        assert customer_action(restored,o,'restore').status_code==200
        slot=slot_for(restarted,o,first)
        response=customer_action(restored,o,'slots/'+slot['id']+'/reprocess')
        assert response.status_code==200,response.text
        claim=restarted.state.worker.claim();assert claim['id']==first['id']
        asyncio.run(restarted.state.worker.execute(claim));saved=order_items(restarted,o)[0]
        assert saved['status']=='completed' and saved['attempt']==1 and saved['raw_result_id']==first['raw_result_id']
        assert restarted_provider.calls==[]
        with restarted.state.db.transaction() as tx:
            assert tx.conn.execute("SELECT COUNT(*) FROM starts WHERE family='openai'").fetchone()[0]==0

def test_missing_result_does_not_starve_other_orders(context):
    app,client,clock,provider=context
    client.patch('/api/admin/settings',json={'max_inflight':16})
    t=template(client);damaged,_=order(client,name='损坏订单',template_ids=[t['id']]);run_all(app)
    d=client.get('/api/customer-orders/'+damaged['id']).json()
    assert customer_action(client,damaged,'submit',slot_ids=[s['id'] for s in d['slots']]).status_code==200
    item=order_items(app,damaged)[0]
    with app.state.db.transaction(readonly=True) as tx:
        asset=tx.get('assets',item['result_id']);raw=tx.get('assets',item['raw_result_id'])
    (app.state.db.root/'assets'/asset['file']).unlink()
    healthy,_=order(client,name='正常订单',template_ids=[t['id']]);run_all(app)
    h=client.get('/api/customer-orders/'+healthy['id']).json()
    assert customer_action(client,healthy,'submit',slot_ids=[s['id'] for s in h['slots']]).status_code==200
    async def run_bounded():
        await app.state.worker.start()
        try:
            for _ in range(50):
                if stored_order(app,healthy).get('delivery_ready'):return
                await asyncio.sleep(.1)
        finally:await app.state.worker.stop()
    asyncio.run(run_bounded())
    assert client.get('/api/customer-orders/'+healthy['id']).json()['delivery_ready']
    assert 'FileNotFoundError' in stored_order(app,damaged)['processing_error']
    assert order_items(app,damaged)[0]['result_id']==asset['id']
    assert (app.state.db.root/'assets'/raw['file']).exists()

class QueueProvider:
    def __init__(self): self.submissions = 0; self.state = 'IN_QUEUE'; self.error = None
    async def submit(self, **kwargs):
        self.submissions += 1
        return dict(fal_request_id=f'job-{self.submissions}', fal_status='IN_QUEUE', fal_status_url='https://queue.fal.run/status', fal_response_url='https://queue.fal.run/result')
    async def poll(self, job):
        if self.error: raise self.error
        return dict(fal_status=self.state, queue_position=3 if self.state=='IN_QUEUE' else None)
    async def result(self, job): return png(size=(1024,1024))


def test_durable_fal_slots_recovery_pause_and_lower_limit(context):
    from backend.app.providers import ProviderFailure
    app, client, clock, _ = context
    p = QueueProvider(); w = app.state.worker; w.provider = p
    o,_ = order(client)
    first = w.claim(); asyncio.run(w.execute(first))
    second = w.claim(); asyncio.run(w.execute(second))
    assert p.submissions == 2
    assert w.claim() is None
    client.patch('/api/admin/settings', json={'max_inflight':1})
    customer_action(client,o,'cancel')
    clock.value += 100000
    recovered = w.claim()
    assert recovered['fal_request_id']=='job-1'
    clock.value += 61
    other = Worker(app.state.db, provider=p, clock=clock); other.recover()
    same = other.claim()
    assert same['fal_request_id']=='job-1'
    p.error = ProviderFailure('timeout','retry',30)
    asyncio.run(other.execute(same))
    assert p.submissions==2
    p.error = None; p.state='COMPLETED'; clock.value += 61
    for _ in range(2): asyncio.run(other.execute(other.claim()))
    assert sum(bool(i.get('raw_result_id')) for i in order_items(app,o))==2
    assert customer_action(client,o,'restore').status_code==200
    for _ in range(2):asyncio.run(other.execute(other.claim()))
    assert sum(i['status']=='completed' for i in order_items(app,o))==2
    assert p.submissions==2


def test_known_request_restart_preserves_identity_and_tracking(context):
    app,client,clock,_=context
    p=QueueProvider();w=app.state.worker;w.provider=p
    o,_=order(client);item=w.claim();asyncio.run(w.execute(item));clock.value+=10
    running=w.claim();assert running['fal_request_id']=='job-1'
    clock.value+=61
    recovered=Worker(app.state.db,provider=p,clock=clock);recovered.recover()
    same=recovered.claim();assert same['id']==item['id'] and same['fal_request_id']=='job-1'
    p.state='COMPLETED';asyncio.run(recovered.execute(same))
    with app.state.db.transaction(readonly=True) as tx:
        saved=tx.get('items',item['id'])
        generation=tx.get('generations',saved['generation_id'])
    assert saved['status']=='completed' and generation['request_id']=='job-1' and p.submissions==1
    slot=slot_for(app,o,saved)
    assert customer_action(client,o,'slots/'+slot['id']+'/rerun').status_code==200
    new=stored_order(app,o)['slots'][0]['active_item_id']
    # Prior queued slots keep their order. The new rerun is a distinct durable item.
    assert new!=item['id'] and next(i for i in order_items(app,o) if i['id']==new).get('fal_request_id') is None

def test_unknown_requires_explicit_resolution_before_rerun(context):
    from backend.app.providers import ProviderFailure
    app,client,clock,provider=context
    o,_=order(client);provider.error=ProviderFailure('ambiguous','unknown')
    item=app.state.worker.claim();asyncio.run(app.state.worker.execute(item));slot=slot_for(app,o,item)
    endpoint='slots/'+slot['id']
    assert customer_action(client,o,endpoint+'/rerun').status_code==409
    assert customer_action(client,o,endpoint+'/retry').status_code==409
    assert customer_action(client,o,endpoint+'/resolve',confirmed_ended=False).status_code==422
    assert customer_action(client,o,endpoint+'/resolve',confirmed_ended=True).status_code==200
    saved=order_items(app,o)[0]
    assert saved['status']=='failed' and saved['remote_reserved'] is False
    assert customer_action(client,o,endpoint+'/rerun').status_code==200

def test_download_retry_never_resubmits_and_disabled_owner_keeps_reservation(context):
    from backend.app.providers import ProviderFailure
    app,client,clock,_=context
    p=QueueProvider(); w=app.state.worker; w.provider=p
    o,_=order(client); item=w.claim(); asyncio.run(w.execute(item))
    with app.state.db.transaction() as tx:
        u=tx.get('users',item['owner']); u['active']=False; tx.put('users',u)
    p.state='COMPLETED'
    async def unavailable(job): raise ProviderFailure('download interrupted','retry')
    p.result=unavailable
    for _ in range(6):
        clock.value+=1000
        claim=w.claim(); assert claim['id']==item['id']
        asyncio.run(w.execute(claim))
    assert p.submissions==1
    with app.state.db.transaction() as tx:
        saved=tx.get('items',item['id'])
        assert saved['fal_status']=='COMPLETED' and saved['remote_reserved']
        assert saved['status']=='queued'


def test_fal_key_does_not_fall_back_to_openai(context,monkeypatch):
    app,client,clock,_=context
    app.state.worker.provider=None
    monkeypatch.delenv('FAL_KEY',raising=False)
    monkeypatch.setenv('OPENAI_API_KEY','not-fal')
    order(client)
    assert app.state.worker.claim() is None
    assert client.get('/api/admin/settings').json()['fal_configured'] is False
    assert client.patch('/api/admin/settings',json={'max_inflight':40}).status_code==200
    assert client.patch('/api/admin/settings',json={'max_inflight':41}).status_code==422


def test_new_claims_not_limited_by_legacy_minute_starts(context):
    app,client,clock,_=context
    order(client)
    with app.state.db.transaction() as tx:
        tx.conn.executemany('INSERT INTO starts(family,at) VALUES(?,?)',[('openai',clock.value)]*1000)
    w=app.state.worker
    for _ in range(8):
        item=w.claim(); assert item
        asyncio.run(w.execute(item))


def test_submission_429_cools_down_all_workers(context):
    from backend.app.providers import ProviderFailure
    app,client,clock,p=context
    order(client); w=app.state.worker
    p.error=ProviderFailure('429','retry',45)
    asyncio.run(w.execute(w.claim()))
    assert Worker(app.state.db,provider=p,clock=clock).claim() is None
    clock.value+=46
    assert w.claim() is not None


def test_cancelled_known_request_is_automatically_recoverable(context):
    app,client,clock,_=context
    p=QueueProvider();w=app.state.worker;w.provider=p
    order(client);asyncio.run(w.execute(w.claim()));clock.value+=10
    async def cancelled(job): raise asyncio.CancelledError()
    p.poll=cancelled
    with pytest.raises(asyncio.CancelledError): asyncio.run(w.execute(w.claim()))
    clock.value+=61
    claim=Worker(app.state.db,provider=p,clock=clock).claim()
    assert claim and claim['fal_request_id']=='job-1'


def test_queued_raw_postprocess_respects_cancel(context):
    app,client,clock,_=context
    o,_=order(client);w=app.state.worker;item=w.claim();asyncio.run(w.execute(item))
    with app.state.db.transaction() as tx:
        value=tx.get('items',item['id']);value.update(status='queued',processing_stage='postprocess');tx.put('items',value)
    assert customer_action(client,o,'cancel').status_code==200
    assert w.claim() is None
    assert customer_action(client,o,'restore').status_code==200
    assert w.claim()['id']==item['id']

def test_completed_remote_failure_releases_slot_without_result_or_resubmit(context):
    app,client,clock,_=context
    p=QueueProvider();w=app.state.worker;w.provider=p
    order(client);item=w.claim();asyncio.run(w.execute(item));clock.value+=10
    async def terminal(job): return dict(fal_status='COMPLETED',fal_error='FAL任务失败，请检查输入或内容限制',queue_position=None)
    async def forbidden(job): pytest.fail('terminal failed job must not download')
    p.poll=terminal;p.result=forbidden
    asyncio.run(w.execute(w.claim()))
    with app.state.db.transaction() as tx:
        value=tx.get('items',item['id'])
    assert value['status']=='failed'
    assert value['fal_status']=='COMPLETED'
    assert value['remote_reserved'] is False
    assert p.submissions==1


def test_print_layout_version_rebuilds_pages_from_saved_results_without_generation(context):
    app,client,_,provider=context
    o,_=order(client);w=app.state.worker;run_all(app);submit_and_publish(app,client,o)
    before=stored_order(app,o);items=order_items(app,o);calls=len(provider.calls)
    with app.state.db.transaction() as tx:
        value=tx.get('orders',o['id']);value['publish_signatures']['_merged']='previous-print-layout';tx.put('orders',value)
    assert w.publish(o['id'])
    after=stored_order(app,o)
    assert len(provider.calls)==calls and order_items(app,o)==items
    assert before['overview_id']==after['overview_id']
    assert [a['id'] for a in before['artifacts']]!=[a['id'] for a in after['artifacts']]
    assert w.publish(o['id']) is False

def test_upload_limit_caps_only_submissions_without_request_id(context):
    app, client, clock, _ = context
    p = QueueProvider(); w = app.state.worker; w.provider = p
    me = client.get('/api/auth/me').json()
    assert client.patch('/api/admin/users/'+me['id']+'/concurrency', json={'generation_concurrency':10,'expected_limit':2}).status_code == 200
    settings = client.patch('/api/admin/settings', json={'max_inflight':16, 'max_uploads':2}).json()
    assert settings['max_uploads'] == 2 and settings['fal_upload_timeout'] == 300
    order(client)
    first, second = w.claim(), w.claim()
    assert first and second and w.claim() is None, 'a third simultaneous upload must wait'
    # Once a submission has a request ID it waits in FAL's queue and frees its upload slot.
    asyncio.run(w.execute(first))
    assert p.submissions == 1
    third = w.claim()
    assert third and not third.get('fal_request_id') and w.claim() is None
    assert client.patch('/api/admin/settings', json={'max_uploads':0}).status_code == 422
    assert client.patch('/api/admin/settings', json={'fal_upload_timeout':29}).status_code == 422
    assert client.patch('/api/admin/settings', json={'fal_upload_timeout':600}).json()['fal_upload_timeout'] == 600
