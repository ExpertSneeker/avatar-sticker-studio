"""OSS synchronization uses synthetic local data and an in-memory remote store."""
import hashlib
import importlib
import importlib.util
import threading
from types import SimpleNamespace
import pytest
from backend.app.db import Database
from backend.app.storage import save_asset


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.fail = False
        self.on_upload = None
        self.on_list = None
        self.uploads = []

    def upload(self, key, body, **kw):
        if self.fail:
            raise RuntimeError('https://secret.invalid/?Signature=do-not-log')
        data = body if isinstance(body, bytes) else body.read()
        self.objects[key] = data
        self.uploads.append(key)
        if self.on_upload:
            self.on_upload()

    def list(self, prefix):
        result = [SimpleNamespace(key=k) for k in self.objects if k.startswith(prefix)]
        if self.on_list:
            self.on_list()
        return result

    def delete(self, key):
        self.objects.pop(key, None)

    def sign(self, key):
        if self.fail:
            raise RuntimeError('https://secret.invalid/?Signature=do-not-log')
        return 'https://test.invalid/' + key + '?signature=synthetic'


@pytest.fixture
def oss(monkeypatch):
    assert importlib.util.find_spec('backend.app.oss_delivery'), 'OSS delivery module not implemented'
    mod = importlib.import_module('backend.app.oss_delivery')
    remote = MemoryStore()
    monkeypatch.setattr(mod, 'create_store', lambda: remote)
    return mod, remote


@pytest.fixture
def submitted(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        asset = save_asset(db, tx, b'synthetic-print', 'staff', 'print')
        artifact = {k: asset[k] for k in ('id', 'url', 'sha256', 'size', 'kind')}
        artifact['path'] = 'print.png'
        tx.put('orders', {'id': 'order-id', 'organization_id': 'org-id', 'state': 'submitted',
                          'delivery_ready': True, 'artifacts': [artifact]})
    return db, artifact, f"print/org-id/order-id/{hashlib.sha256(b'synthetic-print').hexdigest()}.png"


def get_order(db):
    with db.transaction(readonly=True) as tx:
        return tx.get('orders', 'order-id')


def update_order(db, **kw):
    with db.transaction() as tx:
        order = tx.get('orders', 'order-id')
        order.update(kw)
        tx.put('orders', order)


def test_upload_retry_is_idempotent_and_sanitized(oss, submitted, caplog):
    mod, store = oss
    db, artifact, key = submitted
    store.fail = True
    mod.sync(db, now=0)
    assert 'oss_key' not in get_order(db)['artifacts'][0]
    assert 'Signature' not in caplog.text and 'secret.invalid' not in caplog.text
    store.fail = False
    mod.sync(db, now=30)
    mod.sync(db, now=60)
    assert get_order(db)['artifacts'][0]['oss_key'] == key
    assert store.objects == {key: b'synthetic-print'}
    assert len(store.uploads) == 1


def test_upload_io_happens_outside_database_transaction(oss, submitted):
    mod, store = oss
    db, _, _ = submitted
    # A second writer can commit during remote IO, rather than waiting on BEGIN IMMEDIATE.
    store.on_upload = lambda: update_order(db, notes='concurrent change')
    mod.sync(db, now=0)
    assert get_order(db)['notes'] == 'concurrent change'


@pytest.mark.parametrize('change', ['cancel', 'unlock', 'repack', 'hash'])
def test_obsolete_upload_never_updates_current_artifact(oss, submitted, change):
    mod, store = oss
    db, artifact, _ = submitted
    def mutate():
        if change == 'cancel': update_order(db, state='cancelled')
        elif change == 'unlock': update_order(db, delivery_ready=False)
        elif change == 'repack': update_order(db, artifacts=[artifact | {'id': 'new-asset'}])
        else: update_order(db, artifacts=[artifact | {'sha256': '0' * 64}])
    store.on_upload = mutate
    mod.sync(db, now=0)
    assert 'oss_key' not in get_order(db)['artifacts'][0]


def test_repack_cleanup_and_same_hash_reupload_are_safe(oss, submitted):
    mod, store = oss
    db, artifact, key = submitted
    mod.sync(db, now=0)
    stale = 'print/org-id/order-id/' + '0' * 64 + '.png'
    store.objects[stale] = b'obsolete'
    # Current content remains active without a marker while republishing identical bytes.
    update_order(db, artifacts=[artifact | {'id': artifact['id']}])
    mod.sync(db, now=600)
    assert store.objects == {key: b'synthetic-print'}
    assert get_order(db)['artifacts'][0]['oss_key'] == key


def test_cancel_cleanup_clears_marker_and_restore_uploads_again(oss, submitted):
    mod, store = oss
    db, _, key = submitted
    mod.sync(db, now=0)
    update_order(db, state='cancelled')
    mod.sync(db, now=600)
    assert key not in store.objects
    assert 'oss_key' not in get_order(db)['artifacts'][0]
    update_order(db, state='submitted')
    mod.sync(db, now=630)
    assert store.objects[key] == b'synthetic-print'


def test_cleanup_rechecks_candidate_after_remote_list(oss, submitted):
    mod, store = oss
    db, artifact, key = submitted
    store.objects[key] = b'synthetic-print'
    update_order(db, state='cancelled')
    store.on_list = lambda: update_order(db, state='submitted')
    mod.sync(db, now=0)
    assert key in store.objects


def test_hash_mismatch_never_uploads(oss, submitted):
    mod, store = oss
    db, artifact, _ = submitted
    update_order(db, artifacts=[artifact | {'sha256': '0' * 64}])
    mod.sync(db, now=0)
    assert not store.objects and 'oss_key' not in get_order(db)['artifacts'][0]


def test_restart_sync_cannot_overlap_thread_still_uploading(oss, submitted):
    mod, store = oss
    db, _, _ = submitted
    started, release = threading.Event(), threading.Event()
    def blocked():
        started.set()
        assert release.wait(3)
    store.on_upload = blocked
    thread = threading.Thread(target=mod.sync, args=(db,), kwargs={'now': 0})
    thread.start()
    try:
        assert started.wait(3)
        mod.sync(db, now=30)
        assert len(store.uploads) == 1
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()


def test_empty_bucket_disables_without_loading_sdk(monkeypatch):
    assert importlib.util.find_spec('backend.app.oss_delivery'), 'OSS delivery module not implemented'
    mod = importlib.import_module('backend.app.oss_delivery')
    monkeypatch.setenv('STUDIO_OSS_BUCKET', '')
    assert mod.create_store() is None


def test_worker_sync_is_throttled_and_failure_does_not_stop_scheduling(tmp_path, monkeypatch, caplog):
    import asyncio
    from backend.app.worker import Worker
    from backend.app import oss_delivery
    clock = SimpleNamespace(value=1000)
    worker = Worker(Database(tmp_path), clock=lambda: clock.value)
    synced, claimed = [], []
    def sync(db):
        synced.append(clock.value)
        if len(synced) == 1:
            raise RuntimeError('https://secret.invalid/?Signature=do-not-log')
    def claim():
        claimed.append(clock.value)
        return None
    async def sleep(seconds):
        if getattr(worker, 'oss_task', None):
            await worker.oss_task
        clock.value += 10
        if clock.value == 1070:
            worker.stopping = True
    monkeypatch.setattr(oss_delivery, 'sync', sync)
    monkeypatch.setattr(worker, 'heartbeat', lambda: None)
    monkeypatch.setattr(worker, 'recover', lambda: None)
    monkeypatch.setattr(worker, 'unpublished', lambda: [])
    monkeypatch.setattr(worker, 'claim', claim)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    asyncio.run(worker.run())
    assert synced == [1000, 1030, 1060]
    assert claimed == [1000, 1010, 1020, 1030, 1040, 1050, 1060]
    assert 'Signature' not in caplog.text and 'secret.invalid' not in caplog.text


def test_slow_oss_backlog_does_not_block_generation_admission(tmp_path, monkeypatch):
    import asyncio
    from backend.app.worker import Worker
    from backend.app import oss_delivery
    clock = SimpleNamespace(value=1000)
    worker = Worker(Database(tmp_path), clock=lambda: clock.value)
    started, release = threading.Event(), threading.Event()
    uploads, claimed = [], []
    def blocked(db):
        uploads.append(True)
        started.set()
        assert release.wait(3)
    async def scenario():
        real_sleep = asyncio.sleep
        async def sleep(seconds):
            clock.value += 30
            await real_sleep(0.01)
        monkeypatch.setattr(asyncio, 'sleep', sleep)
        task = asyncio.create_task(worker.run())
        try:
            assert await asyncio.to_thread(started.wait, 1)
            await real_sleep(0.08)
            assert len(claimed) >= 3, 'Remote upload blocked generation scheduling'
            assert len(uploads) == 1, 'Overlapping background synchronization'
        finally:
            release.set()
            worker.stopping = True
            await task
            if getattr(worker, 'oss_task', None):
                await worker.oss_task
    monkeypatch.setattr(oss_delivery, 'sync', blocked)
    monkeypatch.setattr(worker, 'heartbeat', lambda: None)
    monkeypatch.setattr(worker, 'recover', lambda: None)
    monkeypatch.setattr(worker, 'unpublished', lambda: [])
    monkeypatch.setattr(worker, 'claim', lambda: claimed.append(True))
    asyncio.run(scenario())


def test_stopping_during_recovery_never_starts_new_oss_task(tmp_path, monkeypatch):
    import asyncio
    from backend.app.worker import Worker
    from backend.app import oss_delivery
    worker = Worker(Database(tmp_path), clock=lambda: 1000)
    uploads = []
    def recovery():
        # stop() can set this while run() is awaiting a threaded recovery.
        worker.stopping = True
    async def no_sleep(seconds):
        pass
    async def scenario():
        await worker.run()
        if worker.oss_task:
            await worker.oss_task
    monkeypatch.setattr(worker, 'heartbeat', lambda: None)
    monkeypatch.setattr(worker, 'recover', recovery)
    monkeypatch.setattr(worker, 'unpublished', lambda: [])
    monkeypatch.setattr(oss_delivery, 'sync', lambda db: uploads.append(True))
    monkeypatch.setattr(asyncio, 'sleep', no_sleep)
    asyncio.run(scenario())
    assert not uploads, 'An OSS upload started after shutdown was requested'


def test_cleanup_waits_ten_minutes_and_failed_delete_clears_marker(oss, submitted, monkeypatch, caplog):
    mod, store = oss
    db, _, key = submitted
    mod.sync(db, now=0)
    update_order(db, state='cancelled')
    mod.sync(db, now=30)
    assert key in store.objects and get_order(db)['artifacts'][0]['oss_key'] == key
    def failed(key):
        raise RuntimeError('https://secret.invalid/?Signature=do-not-log')
    real = store.delete
    monkeypatch.setattr(store, 'delete', failed)
    mod.sync(db, now=600)
    assert key in store.objects and 'oss_key' not in get_order(db)['artifacts'][0]
    assert 'Signature' not in caplog.text and 'secret.invalid' not in caplog.text
    monkeypatch.setattr(store, 'delete', real)
    mod.sync(db, now=1200)
    assert key not in store.objects and 'oss_key' not in get_order(db)['artifacts'][0]


def test_delete_response_loss_then_restart_and_restore_reuploads(oss, submitted, monkeypatch):
    mod, store = oss
    db, _, key = submitted
    mod.sync(db, now=0)
    update_order(db, state='cancelled')
    def lost_response(key):
        store.objects.pop(key)
        raise TimeoutError('remote delete succeeded but response was lost')
    monkeypatch.setattr(store, 'delete', lost_response)
    mod.sync(db, now=600)
    assert key not in store.objects
    assert 'oss_key' not in get_order(db)['artifacts'][0]
    mod._cleanup_times.pop(db, None)  # A fresh process has no reconciliation clock state.
    update_order(db, state='submitted')
    mod.sync(db, now=630)
    assert store.objects[key] == b'synthetic-print'
    assert get_order(db)['artifacts'][0]['oss_key'] == key


def test_sdk_role_bridge_refreshes_and_signs_public_endpoint_with_bounded_timeouts(monkeypatch):
    """Actual SDK signing is offline; only ECS metadata credential retrieval is replaced."""
    from urllib.parse import parse_qs, urlparse
    import alibabacloud_oss_v2 as sdk
    import alibabacloud_credentials.client as credentials_sdk
    from backend.app import oss_delivery as mod
    configurations, credential_calls = [], []
    class InstanceCredentials:
        def __init__(self, config):
            assert config.type == 'ecs_ram_role' and config.role_name == 'synthetic-role'
            assert config.disable_imds_v1 and 0 < config.timeout <= 3000 and 0 < config.connect_timeout <= 3000
        def get_credential(self):
            credential_calls.append(True)
            return SimpleNamespace(access_key_id='synthetic-temporary-id', access_key_secret='synthetic-temporary-secret',
                                   security_token='synthetic-temporary-token')
    real_client = sdk.Client
    def client(config):
        configurations.append(config)
        return real_client(config)
    monkeypatch.setattr(credentials_sdk, 'Client', InstanceCredentials)
    monkeypatch.setattr(sdk, 'Client', client)
    monkeypatch.setenv('STUDIO_OSS_BUCKET', 'synthetic-test')
    monkeypatch.setenv('STUDIO_OSS_RAM_ROLE', 'synthetic-role')
    monkeypatch.setenv('STUDIO_OSS_INTERNAL_ENDPOINT', 'oss-cn-wulanchabu-internal.aliyuncs.com')
    monkeypatch.setenv('STUDIO_OSS_PUBLIC_ENDPOINT', 'oss-cn-wulanchabu.aliyuncs.com')
    monkeypatch.setenv('STUDIO_OSS_URL_TTL', '300')
    mod._configured_store.cache_clear()
    try:
        store = mod.create_store()
        assert not credential_calls
        first = urlparse(store.sign('print/org/order/synthetic.png'))
        second = urlparse(store.sign('print/org/order/synthetic.png'))
        assert first.scheme == 'https' and first.hostname == 'synthetic-test.oss-cn-wulanchabu.aliyuncs.com'
        query = parse_qs(first.query)
        assert query['response-content-disposition'] == ['attachment']
        assert 299 <= int(query['x-oss-expires'][0]) <= 300  # SDK truncates subsecond expiration.
        assert len(credential_calls) == 2
        assert all(0 < c.connect_timeout <= 5 and 0 < c.readwrite_timeout <= 30 and c.retry_max_attempts == 3 for c in configurations)
        assert all(not c.disable_upload_crc64_check and not c.disable_download_crc64_check for c in configurations)
    finally:
        mod._configured_store.cache_clear()
