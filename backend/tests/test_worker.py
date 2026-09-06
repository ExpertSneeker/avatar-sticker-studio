import asyncio
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.worker import Worker
from backend.tests.test_api import png, template, order


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
    client.post('/api/orders/' + o['id'] + '/pause')
    asyncio.run(a.execute(first)); asyncio.run(b.execute(second))
    assert a.claim() is None
    client.post('/api/orders/' + o['id'] + '/resume')
    for _ in range(3): asyncio.run(a.execute(a.claim()))
    clock.value += 61
    abandoned = a.claim()
    assert abandoned
    clock.value += 61
    b.recover()
    result = client.get('/api/orders/' + o['id']).json()
    assert result['unknown'] == 1
    assert next(i for i in result['items'] if i['id'] == abandoned['id'])['status'] == 'unknown'


def test_complete_two_sets_repack_watermark_rerun_and_manifest(context):
    app, client, clock, provider = context
    t1, t2 = template(client, 'A01'), template(client, 'B02')
    o, _ = order(client, template_ids=[t2['id'], t1['id']])
    worker = app.state.worker
    assert hasattr(worker, 'claim'), 'durable worker missing'
    for _ in range(24):
        asyncio.run(worker.execute(worker.claim()))
        clock.value += 61
    result = client.get('/api/orders/' + o['id']).json()
    assert result['status'] == 'completed', result
    manifest = client.get('/api/orders/' + o['id'] + '/manifest').json()
    assert manifest['complete']
    assert [a['path'] for a in manifest['files']] == ['小明_B02_1.png', '小明_B02_2.png', '小明_A01_1.png', '小明_A01_2.png', '小明_水印总览.png']
    assert Image.open(io.BytesIO(client.get(manifest['files'][-1]['url']).content)).size == (1024, 1536)
    before = len(provider.calls)
    r = client.post('/api/orders/' + o['id'] + '/repack', json={'print_settings': {'long_edge_mm': 50}})
    assert r.status_code == 200, r.text
    assert len(client.get('/api/orders/' + o['id'] + '/manifest').json()['files']) == 3
    client.patch('/api/account', json={'watermark': '仅供预览'})
    pages_before = client.get('/api/orders/' + o['id'] + '/manifest').json()['files'][:-1]
    assert client.post('/api/orders/' + o['id'] + '/watermark').status_code == 200
    assert client.get('/api/orders/' + o['id'] + '/manifest').json()['files'][:-1] == pages_before
    assert len(provider.calls) == before
    item = result['items'][0]
    assert client.post(f"/api/orders/{o['id']}/items/{item['id']}/rerun").status_code == 200
    running = client.get('/api/orders/' + o['id']).json()['items'][0]
    assert running['result_url'] == item['result_url']
    asyncio.run(worker.execute(worker.claim()))
    final = client.get('/api/orders/' + o['id']).json()
    assert final['status'] == 'completed'
    assert len(provider.calls) == before + 1
    assert final['items'][0]['result_url'] != item['result_url']
    assert client.get('/api/orders/' + o['id'] + '/download.zip').status_code == 200


def test_unknown_refused_and_retry_are_distinct(context):
    app, client, clock, provider = context
    worker = app.state.worker
    assert hasattr(worker, 'claim'), 'durable worker missing'
    from backend.app.providers import ProviderFailure
    o, _ = order(client)
    provider.error = ProviderFailure('结果待确认', 'unknown')
    asyncio.run(worker.execute(worker.claim()))
    assert client.get('/api/orders/' + o['id']).json()['unknown'] == 1
    provider.error = ProviderFailure('内容拒绝', 'failed')
    asyncio.run(worker.execute(worker.claim()))
    assert client.get('/api/orders/' + o['id']).json()['failed'] == 1
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
    assert client.get('/api/orders/' + o['id']).json()['unknown'] == 1


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
    app, client, clock, provider = context
    o, _ = order(client)
    with app.state.db.transaction() as tx:
        value = tx.get('orders', o['id'])
        value['overview_ready'] = True
        tx.put('orders', value)
    def interrupted_publish(id, **kwargs):
        with app.state.db.transaction() as tx:
            saved = tx.get('orders', id)
        assert saved['overview_ready'] is False
        assert saved['print_settings']['long_edge_mm'] == 50
        return False
    monkeypatch.setattr(app.state.worker, 'publish', interrupted_publish)
    result = client.post('/api/orders/' + o['id'] + '/repack', json={'print_settings': {'long_edge_mm': 50}})
    assert result.status_code == 200


def test_failed_rerun_retains_previous_result_and_artifact_version(context):
    from backend.app.providers import ProviderFailure
    app, client, clock, provider = context
    o, _ = order(client)
    for _ in range(12):
        asyncio.run(app.state.worker.execute(app.state.worker.claim()))
        clock.value += 61
    previous = client.get('/api/orders/' + o['id']).json()
    item = previous['items'][0]
    client.post(f"/api/orders/{o['id']}/items/{item['id']}/rerun")
    provider.error = ProviderFailure('内容被拒绝', 'failed')
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    after = client.get('/api/orders/' + o['id']).json()
    assert after['items'][0]['status'] == 'failed'
    assert after['items'][0]['result_url'] == item['result_url']
    assert after['artifacts'] == previous['artifacts']
    assert after['artifact_version'] == previous['artifact_version']


def test_background_lifecycle_publishes_and_shutdown_releases_worker(tmp_path):
    import time
    provider = Provider()
    app = create_app(tmp_path, provider=provider, start_worker=True)
    with TestClient(app) as client:
        client.post('/api/auth/setup', json={'username': 'admin', 'password': 'safe-password-123', 'display_name': '管理员'})
        client.patch('/api/admin/settings', json={'max_inflight': 16})
        o, _ = order(client)
        deadline = time.monotonic() + 12
        result = None
        while time.monotonic() < deadline:
            result = client.get('/api/orders/' + o['id']).json()
            if result['status'] == 'completed': break
            time.sleep(0.1)
        assert result['status'] == 'completed', result
        assert len(provider.calls) == 12
    with app.state.db.transaction() as tx:
        assert not tx.all('workers')


def test_reprocess_recovers_paid_raw_after_restart_without_openai(context, monkeypatch):
    from backend.app.providers import YeziProvider, ProviderFailure
    app, client, clock, provider = context
    # The entire canvas must be opaque, including its edges.
    async def opaque(**kwargs):
        provider.calls.append(kwargs)
        output = io.BytesIO()
        Image.new('RGB', (1024, 1024), 'red').save(output, 'PNG')
        return output.getvalue()
    monkeypatch.setattr(provider, 'generate', opaque)
    async def failed_cutout(self, data):
        raise ProviderFailure('抠图服务异常，原始生成结果已保留')
    monkeypatch.setattr(YeziProvider, 'cutout', failed_cutout)
    client.patch('/api/admin/settings', json={'cutout_api_key': 'test-cutout-key'})
    o, _ = order(client)
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    first = client.get('/api/orders/' + o['id']).json()['items'][0]
    assert first['status'] == 'failed'
    assert first.get('raw_available') is True
    assert len(provider.calls) == 1
    # Stop the original user queue; a fresh app/worker reads the existing durable raw.
    client.post('/api/orders/' + o['id'] + '/pause')
    restarted_provider = Provider()
    restarted = create_app(app.state.db.root, provider=restarted_provider, clock=clock, start_worker=False)
    async def cutout(self, data):
        assert Image.open(io.BytesIO(data)).getpixel((10, 10)) == (255, 0, 0, 255)
        return png(size=(1024, 1024))
    monkeypatch.setattr(YeziProvider, 'cutout', cutout)
    with TestClient(restarted) as restored:
        restored.post('/api/auth/login', json={'username': 'admin', 'password': 'safe-password-123'})
        restored.patch('/api/admin/settings', json={'cutout_api_key': 'test-cutout-key'})
        response = restored.post(f"/api/orders/{o['id']}/items/{first['id']}/reprocess")
        assert response.status_code == 200, response.text
        restored.post('/api/orders/' + o['id'] + '/resume')
        claim = restarted.state.worker.claim()
        assert claim['id'] == first['id']
        asyncio.run(restarted.state.worker.execute(claim))
        item = restored.get('/api/orders/' + o['id']).json()['items'][0]
        assert item['status'] == 'completed'
        assert item['attempt'] == 1
        assert item['raw_available'] is True
        assert item['processing_stage'] == 'postprocess'
        assert restarted_provider.calls == []
        with restarted.state.db.transaction() as tx:
            assert tx.conn.execute("SELECT COUNT(*) FROM starts WHERE family='openai'").fetchone()[0] == 0


def test_missing_result_does_not_starve_other_orders(context):
    app, client, clock, provider = context
    client.patch('/api/admin/settings', json={'max_inflight': 16})
    t = template(client)
    damaged, _ = order(client, name='损坏订单', template_ids=[t['id']])
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    client.post('/api/orders/' + damaged['id'] + '/pause')
    with app.state.db.transaction() as tx:
        item = next(i for i in tx.all('items') if i['order_id'] == damaged['id'] and i['status'] == 'completed')
        asset = tx.get('assets', item['result_id'])
        raw = tx.get('assets', item['raw_result_id'])
    (app.state.db.root / 'assets' / asset['file']).unlink()
    healthy, _ = order(client, name='正常订单', template_ids=[t['id']])
    async def run_bounded():
        await app.state.worker.start()
        try:
            for _ in range(50):
                with app.state.db.transaction() as tx:
                    current = tx.get('orders', healthy['id'])
                if current.get('overview_ready'): return
                await asyncio.sleep(0.1)
        finally:
            await app.state.worker.stop()
    asyncio.run(run_bounded())
    result = client.get('/api/orders/' + healthy['id']).json()
    assert result['status'] == 'completed', result
    broken = client.get('/api/orders/' + damaged['id']).json()
    assert 'FileNotFoundError' in broken['processing_error']
    assert broken['items'][0]['result_url'] == asset['url']
    assert (app.state.db.root / 'assets' / raw['file']).exists()


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
    client.post('/api/orders/'+o['id']+'/pause')
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
    result=client.get('/api/orders/'+o['id']).json()
    assert result['completed']==2
    assert p.submissions==2


def test_known_unknown_recover_and_rerun_identity(context):
    from backend.app.providers import ProviderFailure
    app,client,clock,_=context
    p=QueueProvider(); w=app.state.worker; w.provider=p
    o,_=order(client); item=w.claim(); asyncio.run(w.execute(item)); clock.value+=10
    p.error=ProviderFailure('auth','unknown'); asyncio.run(w.execute(w.claim()))
    endpoint=f"/api/orders/{o['id']}/items/{item['id']}"
    assert client.post(endpoint+'/rerun').status_code==409
    info=client.get('/api/orders/'+o['id']).json()['items'][0]
    assert info['recoverable'] is True
    assert client.post(endpoint+'/recover').status_code==200
    p.error=None; p.state='COMPLETED'; asyncio.run(w.execute(w.claim()))
    assert client.post(endpoint+'/rerun').status_code==200
    asyncio.run(w.execute(w.claim()))
    assert p.submissions==2
    assert client.get('/api/orders/'+o['id']).json()['items'][0]['fal_request_id']=='job-2'


def test_unknown_requires_explicit_resolution_before_rerun(context):
    from backend.app.providers import ProviderFailure
    app,client,clock,provider=context
    o,_=order(client)
    provider.error=ProviderFailure('ambiguous','unknown')
    item=app.state.worker.claim(); asyncio.run(app.state.worker.execute(item))
    url=f"/api/orders/{o['id']}/items/{item['id']}"
    assert client.post(url+'/rerun').status_code==409
    assert client.post(url+'/resolve',json={'confirmed_ended':False}).status_code==422
    assert client.post(url+'/resolve',json={'confirmed_ended':True}).status_code==200
    with app.state.db.transaction() as tx:
        saved=tx.get('items',item['id'])
        assert saved['remote_reserved'] is False
        assert saved['resolution_history'][0]['resolved_at']==clock.value
    assert client.post(url+'/rerun').status_code==200


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


def test_queued_raw_postprocess_respects_pause(context):
    app,client,clock,_=context
    o,_=order(client);w=app.state.worker
    item=w.claim();asyncio.run(w.execute(item))
    client.post('/api/orders/'+o['id']+'/pause')
    assert client.post(f"/api/orders/{o['id']}/items/{item['id']}/reprocess").status_code==200
    assert w.claim() is None
