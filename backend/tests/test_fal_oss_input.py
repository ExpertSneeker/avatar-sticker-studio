"""Synthetic OSS/FAL transports only; never use external providers or credentials."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import logging
import subprocess
import sys
import threading
import time

import httpx
import pytest
from alibabacloud_oss_v2.exceptions import ServiceError
from backend.app import oss_delivery, providers
from backend.tests.helpers import order, png
from backend.tests.test_providers import install
from backend.tests.test_worker import context


def service_error(**kw):
    return ServiceError(request_id="synthetic", message="safe", ec="", timestamp="", request_target="", **kw)


class Store:
    bucket = 'synthetic'

    def __init__(self):
        self.objects = {}; self.uploads = []; self.signatures = []; self.error = None

    def head(self, key):
        if self.error:
            raise self.error
        if key not in self.objects:
            raise service_error(status_code=404, code='NoSuchKey')
        return oss_delivery.ObjectInfo(key)

    def upload(self, key, body, **kw):
        self.uploads.append((key, body, kw))
        self.objects[key] = body

    def sign_input(self, key, ttl):
        self.signatures.append((key, ttl))
        return 'https://synthetic.oss.test/' + key + '?Signature=DO-NOT-LOG'


def test_stage_daily_content_keys_and_reuse(monkeypatch):
    class FixedDate(datetime):
        day = 5
        @classmethod
        def now(cls, tz=None):
            assert tz == timezone.utc
            return cls(2026, 10, cls.day, tzinfo=tz)
    monkeypatch.setattr(oss_delivery, 'datetime', FixedDate, raising=False)
    store = Store(); stats = {}
    key = oss_delivery.stage_fal_input(store, b'image', stats=stats)
    assert key == 'fal-inputs/20261005/' + hashlib.sha256(b'image').hexdigest() + '.png'
    assert stats['reused'] is False
    assert oss_delivery.stage_fal_input(store, b'image', stats=stats) == key
    assert stats['reused'] is True and len(store.uploads) == 1
    assert store.uploads[0][2]['content_type'] == 'image/png'
    FixedDate.day = 6
    assert oss_delivery.stage_fal_input(store, b'image') != key
    assert len(store.uploads) == 2


@pytest.mark.parametrize('error', [service_error(status_code=403, code='AccessDenied'),
    service_error(status_code=404, code='NoSuchBucket'), RuntimeError('signed URL DO-NOT-LOG')])
def test_stage_head_failure_does_not_upload(error):
    store = Store(); store.error = error
    with pytest.raises(type(error)):
        oss_delivery.stage_fal_input(store, b'image')
    assert not store.uploads


def test_stage_concurrent_same_key_one_put_and_other_keys_parallel():
    store = Store(); first_upload = threading.Event(); other_upload = threading.Event()
    original = store.upload
    def upload(key, body, **kw):
        if body == b'first':
            first_upload.set()
            assert other_upload.wait(2), 'distinct keys must not share an IO lock'
        else:
            assert first_upload.wait(2)
            other_upload.set()
        time.sleep(.02)
        original(key, body, **kw)
    store.upload = upload
    with ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(oss_delivery.stage_fal_input, store, data)
                   for data in (b'first', b'first', b'other', b'first')]
        keys = [f.result() for f in futures]
    assert keys[0] == keys[1] == keys[3] and keys[2] != keys[0]
    assert len(store.uploads) == 2
    assert not oss_delivery._input_locks, 'per-key lock registry must release idle entries'


def test_sign_input_uses_public_get_without_download_header():
    class Public:
        def presign(self, request, **kw):
            assert request.bucket == 'synthetic' and request.key == 'fal-inputs/key.png'
            assert request.response_content_disposition is None
            assert kw['expires'].total_seconds() == 7200
            return type('Signed', (), {'url': 'https://synthetic.test/signed'})()
    store = oss_delivery.OSSStore('synthetic', None, Public(), 300)
    assert store.sign_input('fal-inputs/key.png', 7200) == 'https://synthetic.test/signed'


@pytest.mark.parametrize('mode', ['inline', 'oss'])
def test_provider_exact_body_bytes_and_metrics(monkeypatch, mode):
    seen = []
    install(monkeypatch, lambda r: (seen.append(r) or httpx.Response(200, json={'request_id':'job-1'})))
    images = ['https://synthetic.test/template?Signature=DO-NOT-LOG', 'https://synthetic.test/avatar?Signature=DO-NOT-LOG']
    kw = {'image_urls':images} if mode == 'oss' else {}
    job = asyncio.run(providers.FalProvider('synthetic').submit(b'template', b'avatar', '固定提示词', **kw))
    expected = dict(prompt='固定提示词', image_urls=images if mode == 'oss' else [
        'data:image/png;base64,' + base64.b64encode(x).decode() for x in (b'template', b'avatar')],
        image_size={'width':1024,'height':1024}, quality='low', num_images=1,
        background='transparent', output_format='png', sync_mode=False)
    assert seen[0].content == httpx.Request('POST', providers.FalProvider.endpoint, json=expected).content
    assert job['fal_input'] == mode
    assert job['fal_submit_metrics']['request_bytes'] == len(seen[0].content)
    assert job['fal_submit_metrics']['post_ms'] >= 0
    assert 'DO-NOT-LOG' not in json.dumps(job)


@pytest.mark.parametrize('status', ['failed', 'unknown', 'retry'])
def test_submit_failure_retains_safe_metrics(monkeypatch, status):
    seen = []
    def receive(r):
        seen.append(r)
        if status == 'unknown': raise httpx.ReadTimeout('DO-NOT-LOG', request=r)
        return httpx.Response(429 if status == 'retry' else 400)
    install(monkeypatch, receive)
    with pytest.raises(providers.ProviderFailure) as exc:
        asyncio.run(providers.FalProvider('synthetic').submit(b'a', b'b', 'p', image_urls=['https://synthetic.test/a?Signature=DO-NOT-LOG']*2))
    assert exc.value.status == status
    assert exc.value.submit_metrics['request_bytes'] == len(seen[0].content)
    assert exc.value.submit_metrics['post_ms'] >= 0
    assert 'DO-NOT-LOG' not in str(exc.value.submit_metrics)


def configure_worker(context, monkeypatch, store, mode='oss'):
    app, client, clock, _ = context
    worker = app.state.worker
    worker.provider = providers.FalProvider('synthetic')
    monkeypatch.setattr(oss_delivery, 'create_store', lambda:store)
    with app.state.db.transaction() as tx:
        config = tx.get('config', 'settings'); config['fal_input_mode'] = mode; tx.put('config', config)
    order(client)
    return app, worker, clock


@pytest.fixture(autouse=True)
def capture_timing(caplog):
    logger = logging.getLogger('backend.app.worker.timing')
    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)


def events(caplog):
    return [json.loads(r.message) for r in caplog.records if r.name == 'backend.app.worker.timing' and r.message.startswith('{')]


@pytest.mark.parametrize('failure', [False, True, 'not-configured'])
def test_worker_oss_staging_or_inline_fallback(context, monkeypatch, caplog, failure):
    store = Store()
    if failure is True: store.error = RuntimeError('https://synthetic.test/?Signature=DO-NOT-LOG')
    app, worker, clock = configure_worker(context, monkeypatch, None if failure == 'not-configured' else store)
    monkeypatch.setenv('STUDIO_FAL_INPUT_URL_TTL', '1234')
    bodies = []
    install(monkeypatch, lambda r: (bodies.append(json.loads(r.content)) or httpx.Response(200, json={'request_id':'job-1'})))
    caplog.set_level('INFO', logger='backend.app.worker')
    item = worker.claim(); asyncio.run(worker.execute(item))
    with app.state.db.transaction(readonly=True) as tx:
        saved = tx.get('items', item['id'])
    assert saved['fal_input'] == ('inline' if failure else 'oss')
    assert saved['status'] == 'queued' and saved['attempt'] == 1
    if failure:
        assert all(x.startswith('data:image/png;base64,') for x in bodies[0]['image_urls'])
        assert saved['fal_input_fallback_reason'] in ('oss_stage_failed', 'oss_not_configured')
    else:
        assert all(x.startswith('https://synthetic.oss.test/') for x in bodies[0]['image_urls'])
        assert len(store.signatures) == 2 and all(ttl == 1234 for _, ttl in store.signatures)
    submit = next(e for e in events(caplog) if e['event'] == 'fal_submit')
    assert submit['mode'] == ('fallback' if failure else 'oss') and submit['stage_ms'] >= 0
    assert submit['request_bytes'] > 0 and submit['post_ms'] >= 0
    assert 'DO-NOT-LOG' not in str(events(caplog)) and 'DO-NOT-LOG' not in str(saved)


def test_worker_submit_failed_logs_and_keeps_inline_on_fallback(context, monkeypatch, caplog):
    store = Store(); store.error = RuntimeError('DO-NOT-LOG')
    app, worker, clock = configure_worker(context, monkeypatch, store)
    install(monkeypatch, lambda r:httpx.Response(429, headers={'retry-after':'45'}))
    caplog.set_level('INFO', logger='backend.app.worker')
    item = worker.claim(); asyncio.run(worker.execute(item))
    with app.state.db.transaction(readonly=True) as tx:
        saved = tx.get('items', item['id'])
    assert saved['fal_input'] == 'inline' and saved['status'] == 'queued'
    assert saved['next_at'] == clock.value + 45
    submit = next(e for e in events(caplog) if e['event'] == 'fal_submit')
    assert submit['mode'] == 'fallback' and submit['outcome'] == 'retry'
    assert submit['request_bytes'] > 0 and submit['post_ms'] >= 0


def test_worker_known_request_never_stages_and_logs_poll_download_processing(context, monkeypatch, caplog):
    app, worker, clock = configure_worker(context, monkeypatch, Store())
    handler = [lambda r:httpx.Response(200, json={'request_id':'job-1'})]
    install(monkeypatch, lambda r:handler[0](r))
    item = worker.claim(); asyncio.run(worker.execute(item))
    monkeypatch.setattr(oss_delivery, 'create_store', lambda:pytest.fail('known request must not stage or sign'))
    clock.value += 10
    states = iter(['IN_PROGRESS', 'COMPLETED'])
    def receive(r):
        assert r.method == 'GET'
        if r.url.path.endswith('/status'): return httpx.Response(200, json={'status':next(states),'queue_position':2})
        if r.url.host == 'queue.fal.run': return httpx.Response(200, json={'images':[{'url':'https://v3.fal.media/result.png'}]})
        return httpx.Response(200, content=png(size=(1024,1024)))
    handler[0] = receive
    caplog.set_level('INFO', logger='backend.app.worker')
    asyncio.run(worker.execute(worker.claim())); clock.value += 10
    asyncio.run(worker.execute(worker.claim()))
    with app.state.db.transaction(readonly=True) as tx:
        saved = tx.get('items', item['id'])
    assert saved['status'] == 'completed'
    polls = [e for e in events(caplog) if e['event'] == 'fal_poll']
    assert [e['status'] for e in polls] == ['IN_PROGRESS','COMPLETED']
    assert all(e['queue_position'] == 2 and e['at'] >= 1000 for e in polls)
    assert next(e for e in events(caplog) if e['event'] == 'fal_result')['download_ms'] >= 0
    assert next(e for e in events(caplog) if e['event'] == 'fal_postprocess_complete')['postprocess_ms'] >= 0


@pytest.mark.parametrize('mode', ['inline','oss'])
def test_admission_and_rate_backoff_match_in_both_modes(context, monkeypatch, mode):
    app, worker, clock = configure_worker(context, monkeypatch, Store(), mode)
    with app.state.db.transaction() as tx:
        settings = tx.get('config','settings'); settings.update(max_inflight=3,max_uploads=1); tx.put('config',settings)
        users = tx.all('users'); user = users[0]; user['generation_concurrency']=2; tx.put('users',user)
    install(monkeypatch, lambda r:httpx.Response(200,json={'request_id':'job-'+str(time.monotonic_ns())}))
    first = worker.claim(); assert first and worker.claim() is None
    asyncio.run(worker.execute(first))
    second = worker.claim(); assert second and worker.claim() is None
    asyncio.run(worker.execute(second))
    assert worker.claim() is None, 'account cap still reserves known requests'
    with app.state.db.transaction() as tx:
        user = tx.get('users',first['owner']); user['generation_concurrency']=10; tx.put('users',user)
    third = worker.claim(); assert third
    asyncio.run(worker.execute(third))
    assert worker.claim() is None, 'global cap still reserves known requests'


@pytest.mark.parametrize('mode', ['inline','oss'])
def test_worker_unknown_and_unsent_submit_boundaries_match(context, monkeypatch, caplog, mode):
    app, worker, clock = configure_worker(context, monkeypatch, Store(), mode)
    outcomes = iter([httpx.ConnectTimeout, httpx.ReadTimeout])
    def receive(r):
        raise next(outcomes)('https://synthetic.test/?Signature=DO-NOT-LOG',request=r)
    install(monkeypatch, receive)
    caplog.set_level('INFO', logger='backend.app.worker')
    first = worker.claim(); asyncio.run(worker.execute(first))
    second = worker.claim(); asyncio.run(worker.execute(second))
    with app.state.db.transaction(readonly=True) as tx:
        a,b = [tx.get('items', i['id']) for i in (first,second)]
    assert a['status']=='failed' and not a['remote_reserved']
    assert b['status']=='unknown' and b['remote_reserved']
    assert a['fal_input']==b['fal_input']==mode
    submissions=[e for e in events(caplog) if e['event']=='fal_submit']
    assert [e['outcome'] for e in submissions]==['failed','unknown']
    assert all(e['request_bytes']>0 and e['post_ms']>=0 for e in submissions)
    assert 'DO-NOT-LOG' not in str(a)+str(b)+str(events(caplog))


@pytest.mark.parametrize('mode', ['inline','oss'])
def test_worker_429_backoff_blocks_new_submissions(context, monkeypatch, mode):
    app, worker, clock = configure_worker(context, monkeypatch, Store(), mode)
    install(monkeypatch, lambda r:httpx.Response(429,headers={'retry-after':'45'}))
    item=worker.claim(); asyncio.run(worker.execute(item))
    with app.state.db.transaction(readonly=True) as tx:
        saved=tx.get('items',item['id']); settings=tx.get('config','settings')
    assert saved['status']=='queued' and saved['next_at']==clock.value+45
    assert settings['fal_retry_at']==clock.value+45 and not saved['remote_reserved']
    assert worker.claim() is None
    clock.value+=46
    assert worker.claim()


def test_worker_completed_input_fetch_failure_is_terminal(context, monkeypatch):
    app, worker, clock = configure_worker(context, monkeypatch, Store())
    def receive(r):
        if r.method=='POST': return httpx.Response(200,json={'request_id':'job-1'})
        assert r.url.path.endswith('/status'), 'FAL fetch error must not download or resubmit'
        return httpx.Response(200,json={'status':'COMPLETED','error':'Fetch failed DO-NOT-LOG','error_type':'input_fetch_error'})
    install(monkeypatch,receive)
    item=worker.claim(); asyncio.run(worker.execute(item)); clock.value+=10
    asyncio.run(worker.execute(worker.claim()))
    with app.state.db.transaction(readonly=True) as tx:
        saved=tx.get('items',item['id'])
    assert saved['status']=='failed' and not saved['remote_reserved']
    assert saved['error']=='FAL任务失败，请检查输入或内容限制'


def test_structured_timing_is_emitted_once_with_default_warning_root():
    code = """
import logging
from backend.app.worker import Worker
logging.getLogger().setLevel(logging.WARNING)
worker = object.__new__(Worker)
worker.clock = lambda: 1234
worker.timing('fal_submit', {'id':'synthetic'}, mode='oss', request_bytes=123)
assert logging.getLogger('httpx').getEffectiveLevel() >= logging.WARNING
"""
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, check=True)
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {'event':'fal_submit','item_id':'synthetic','at':1234,'mode':'oss','request_bytes':123}


@pytest.mark.parametrize('change',['cancel','hold','pause','disable-owner','disable-org','recover'])
def test_staging_revalidates_claim_and_policy_before_post(context,monkeypatch,change):
    from backend.app.worker import Worker
    from backend.tests.helpers import customer_action
    app,worker,clock=configure_worker(context,monkeypatch,Store())
    entered,release=threading.Event(),threading.Event();original=oss_delivery.stage_fal_input
    def blocked(*args,**kw):
        entered.set();assert release.wait(3);return original(*args,**kw)
    monkeypatch.setattr(oss_delivery,'stage_fal_input',blocked)
    sent=[]
    install(monkeypatch,lambda r:(sent.append(r) or httpx.Response(200,json={'request_id':'job-1'})))
    item=worker.claim()
    async def go():
        task=asyncio.create_task(worker.execute(item))
        try:
            for _ in range(2000):
                if entered.is_set():break
                await asyncio.sleep(.001)
            assert entered.is_set()
            if change=='cancel':assert customer_action(context[1],{'id':item['order_id']},'cancel').status_code==200
            elif change=='recover':
                clock.value+=31;Worker(app.state.db,provider=worker.provider,clock=clock).recover()
            else:
                with app.state.db.transaction() as tx:
                    if change in ('hold','pause'):
                        order=tx.get('orders',item['order_id']);order['integration_holds']=['synthetic'] if change=='hold' else []
                        if change=='pause':order['paused']=True
                        tx.put('orders',order)
                    elif change=='disable-owner':
                        account=tx.get('users',item['owner']);account['active']=False;tx.put('users',account)
                    else:
                        order=tx.get('orders',item['order_id']);org=tx.get('organizations',order['organization_id']);org['active']=False;tx.put('organizations',org)
        finally:release.set()
        await task
    asyncio.run(go())
    with app.state.db.transaction(readonly=True) as tx:saved=tx.get('items',item['id'])
    assert not sent,'obsolete or policy-blocked execution must not send a paid POST'
    if change=='recover':assert saved['status']=='unknown' and saved['remote_reserved'] and not saved.get('fal_request_id')
    else:assert saved['status']=='queued' and not saved['remote_reserved'] and not saved.get('fal_request_id')


@pytest.mark.parametrize('phase',['stage','sign'])
def test_cancel_before_submit_requeues_without_phantom_request(context,monkeypatch,phase):
    store=Store();app,worker,clock=configure_worker(context,monkeypatch,store)
    entered,release=threading.Event(),threading.Event()
    target=oss_delivery if phase=='stage' else store
    attr='stage_fal_input' if phase=='stage' else 'sign_input';original=getattr(target,attr)
    def blocked(*args,**kw):entered.set();assert release.wait(3);return original(*args,**kw)
    monkeypatch.setattr(target,attr,blocked)
    sent=[];install(monkeypatch,lambda r:(sent.append(r) or httpx.Response(200,json={'request_id':'job-1'})))
    item=worker.claim()
    async def go():
        task=asyncio.create_task(worker.execute(item))
        try:
            for _ in range(2000):
                if entered.is_set():break
                await asyncio.sleep(.001)
            assert entered.is_set();task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        finally:release.set()
    asyncio.run(go())
    with app.state.db.transaction(readonly=True) as tx:saved=tx.get('items',item['id'])
    assert not sent and saved['status']=='queued' and not saved['remote_reserved'] and not saved.get('fal_request_id')
    clock.value+=31
    from backend.app.worker import Worker
    recovered=Worker(app.state.db,provider=worker.provider,clock=clock);recovered.recover()
    assert recovered.claim()['id']==item['id']


def test_cancel_after_entering_submit_remains_unknown(context,monkeypatch):
    app,worker,clock=configure_worker(context,monkeypatch,Store())
    async def cancelled(*args,**kw):raise asyncio.CancelledError()
    monkeypatch.setattr(worker.provider,'submit',cancelled)
    item=worker.claim()
    with pytest.raises(asyncio.CancelledError):asyncio.run(worker.execute(item))
    with app.state.db.transaction(readonly=True) as tx:saved=tx.get('items',item['id'])
    assert saved['status']=='unknown' and saved['remote_reserved'] and not saved.get('fal_request_id')


@pytest.mark.parametrize('inner',[service_error(status_code=404,code='NoSuchKey'),
    service_error(status_code=403,code='AccessDenied'),service_error(status_code=404,code='NoSuchBucket'),
    RuntimeError('404 NoSuchKey DO-NOT-LOG')])
def test_sdk_wrapped_missing_key_only_uploads_proven_absence(inner):
    from alibabacloud_oss_v2.exceptions import OperationError
    store=Store();store.error=OperationError(name='HeadObject',error=inner)
    if isinstance(inner,ServiceError) and inner.status_code==404 and inner.code=='NoSuchKey':
        assert oss_delivery.stage_fal_input(store,b'image').startswith('fal-inputs/')
        assert len(store.uploads)==1
    else:
        with pytest.raises(OperationError):oss_delivery.stage_fal_input(store,b'image')
        assert not store.uploads
