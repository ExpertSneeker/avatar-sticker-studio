"""Deployment regressions use isolated data roots and fake image providers only."""
import asyncio
import io
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.providers import ProviderFailure, YeziProvider
from backend.app.storage import save_asset
from backend.app.worker import Worker
from backend.tests.test_api import order, png
from backend.tests.test_worker import Clock, Provider, context


def seed_raw(app, item, **fields):
    output = io.BytesIO()
    Image.new('RGB', (1024, 1024), 'red').save(output, 'PNG')
    with app.state.db.transaction() as tx:
        raw = save_asset(app.state.db, tx, output.getvalue(), item['owner'], 'raw_result', order_id=item['order_id'])
        latest = tx.get('items', item['id'])
        latest.update(raw_result_id=raw['id'], processing_stage='postprocess', remote_reserved=False, **fields)
        tx.put('items', latest)
    return latest


def saved(app, item):
    with app.state.db.transaction() as tx:
        return tx.get('items', item['id'])


def test_crashed_cutout_requires_manual_reprocess_and_retains_assets(context, monkeypatch):
    app, client, clock, provider = context
    o, _ = order(client)
    w = app.state.worker
    item = w.claim()
    seed_raw(app, item, cutout_inflight=True, fal_request_id='paid-fal-job', result_id='last-good', result_url='/last-good')
    clock.value += 31
    recovered = Worker(app.state.db, provider=provider, clock=clock)
    recovered.recover()
    value = saved(app, item)
    assert value['status'] == 'unknown'
    assert value['cutout_inflight'] is True
    assert value['remote_reserved'] is False
    assert value['result_id'] == 'last-good'
    assert value['raw_result_id']
    endpoint = f"/api/orders/{o['id']}/items/{item['id']}"
    info = client.get('/api/orders/' + o['id']).json()['items'][0]
    assert info['recoverable'] is False
    assert client.post(endpoint + '/recover').status_code == 409
    # Resolving the uncertainty does not authorize another cutout by itself.
    assert client.post(endpoint + '/resolve', json={'confirmed_ended': True}).status_code == 200
    assert saved(app, item)['cutout_inflight'] is True
    assert client.post(endpoint + '/reprocess').status_code == 200
    assert not saved(app, item).get('cutout_inflight')
    calls = []
    async def cutout(self, data):
        calls.append(data)
        assert saved(app, item)['cutout_inflight'] is True
        return png(size=(1024, 1024))
    monkeypatch.setattr(YeziProvider, 'cutout', cutout)
    client.patch('/api/admin/settings', json={'cutout_api_key': 'fake'})
    claim = recovered.claim()
    assert claim['id'] == item['id']
    asyncio.run(recovered.execute(claim))
    value = saved(app, item)
    assert value['status'] == 'completed'
    assert not value.get('cutout_inflight')
    assert value['raw_result_id']
    assert len(calls) == 1 and provider.calls == []


@pytest.mark.parametrize('outcome', ['cancel', 'retry', 'unexpected'])
def test_cutout_marker_commits_before_request_and_blocks_automatic_retry(context, monkeypatch, outcome):
    app, client, clock, provider = context
    order(client)
    w = app.state.worker
    item = w.claim()
    item = seed_raw(app, item, fal_request_id='already-paid')
    client.patch('/api/admin/settings', json={'cutout_api_key': 'fake'})
    async def interrupted(self, data):
        assert saved(app, item)['cutout_inflight'] is True
        if outcome == 'cancel':
            raise asyncio.CancelledError()
        if outcome == 'retry':
            raise ProviderFailure('ambiguous retry', 'retry')
        raise RuntimeError('lost response')
    monkeypatch.setattr(YeziProvider, 'cutout', interrupted)
    if outcome == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(w.execute(item))
    else:
        asyncio.run(w.execute(item))
    value = saved(app, item)
    assert value['status'] in {'unknown', 'failed'}
    assert value['cutout_inflight'] is True
    assert value['raw_result_id']
    assert value['remote_reserved'] is False
    clock.value += 1000
    w.recover()
    assert saved(app, item)['status'] != 'queued'
    assert provider.calls == []


def test_raw_without_cutout_started_resumes_automatically(context, monkeypatch):
    app, client, clock, provider = context
    order(client)
    item = app.state.worker.claim()
    seed_raw(app, item)
    clock.value += 31
    restarted = Worker(app.state.db, provider=provider, clock=clock)
    restarted.recover()
    claim = restarted.claim()
    assert claim['id'] == item['id']
    assert claim['processing_stage'] == 'postprocess'
    assert not claim.get('cutout_inflight')
    async def cutout(self, data):
        return png(size=(1024, 1024))
    monkeypatch.setattr(YeziProvider, 'cutout', cutout)
    client.patch('/api/admin/settings', json={'cutout_api_key': 'fake'})
    asyncio.run(restarted.execute(claim))
    assert saved(app, item)['status'] == 'completed'
    assert provider.calls == []


def test_graceful_stop_preserves_cutout_uncertainty(context, monkeypatch):
    app, client, clock, provider = context
    order(client)
    w = app.state.worker
    item = seed_raw(app, w.claim(), fal_request_id='already-paid')
    client.patch('/api/admin/settings', json={'cutout_api_key': 'fake'})
    async def run_and_stop():
        started = asyncio.Event()
        async def cutout(self, data):
            started.set()
            await asyncio.Future()
        monkeypatch.setattr(YeziProvider, 'cutout', cutout)
        task = asyncio.create_task(w.execute(item))
        w.tasks.add(task)
        await asyncio.wait_for(started.wait(), timeout=2)
        await w.stop()
        assert task.cancelled()
    asyncio.run(run_and_stop())
    value = saved(app, item)
    assert value['status'] == 'unknown'
    assert value['cutout_inflight'] and value['raw_result_id']
    assert value['remote_reserved'] is False
    restarted = Worker(app.state.db, provider=provider, clock=clock)
    restarted.recover()
    assert saved(app, item)['status'] == 'unknown'
    assert provider.calls == []


def test_publish_serializes_across_worker_instances_without_duplicate_pack(context, monkeypatch):
    app, client, clock, provider = context
    o, _ = order(client)
    with app.state.db.transaction() as tx:
        asset = save_asset(app.state.db, tx, png(size=(1024, 1024)), tx.get('orders', o['id'])['owner'], 'result', order_id=o['id'])
        for item in tx.all('items'):
            item.update(status='completed', result_id=asset['id'])
            tx.put('items', item)
    entered, release, second_started, duplicate = (threading.Event() for _ in range(4))
    calls = []
    def pack(*args):
        calls.append(1)
        if len(calls) > 1:
            duplicate.set()
        entered.set()
        assert release.wait(5)
        return [('fake.png', png())]
    monkeypatch.setattr('backend.app.worker.pack_set', pack)
    monkeypatch.setattr('backend.app.worker.overview', lambda *args: png())
    second = Worker(app.state.db, provider=provider, clock=clock)
    def publish_second():
        second_started.set()
        return second.publish(o['id'])
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(app.state.worker.publish, o['id'])
        assert entered.wait(5)
        following = pool.submit(publish_second)
        assert second_started.wait(5)
        try:
            assert not duplicate.wait(0.1), 'second publisher allocated a duplicate pack'
        finally:
            release.set()
        assert first.result(timeout=5) is True
        assert following.result(timeout=5) is False
    assert len(calls) == 1
    assert client.get('/api/orders/' + o['id']).json()['artifact_version'] == 1


def test_ready_requires_database_and_live_worker(tmp_path, monkeypatch):
    clock = Clock()
    app = create_app(tmp_path, provider=Provider(), clock=clock)
    with TestClient(app) as client:
        assert client.get('/api/ready').status_code == 200
        # A fresh lease in another process must not hide this worker's failure.
        app.state.worker.stopping = True
        assert client.get('/api/ready').status_code == 503
        app.state.worker.stopping = False
        with app.state.db.transaction() as tx:
            tx.put('workers', {'id': app.state.worker.id, 'expires': clock.value - 1})
        assert client.get('/api/ready').status_code == 503
        app.state.worker.heartbeat()
        assert client.get('/api/ready').status_code == 200
        original = app.state.db.transaction
        def broken_db():
            raise RuntimeError('secret database path and password')
        monkeypatch.setattr(app.state.db, 'transaction', broken_db)
        response = client.get('/api/ready')
        assert response.status_code == 503
        assert 'secret' not in response.text
        assert client.get('/api/health').status_code == 200
        monkeypatch.setattr(app.state.db, 'transaction', original)
        async def stop_scheduler():
            app.state.worker.loop_task.cancel()
            await asyncio.gather(app.state.worker.loop_task, return_exceptions=True)
        client.portal.call(stop_scheduler)
        app.state.worker.heartbeat()
        assert client.get('/api/ready').status_code == 503
    assert app.state.worker.stopping
    inactive = create_app(tmp_path / 'inactive', start_worker=False)
    with TestClient(inactive) as client:
        inactive.state.worker.heartbeat()
        assert client.get('/api/ready').status_code == 503


def test_setup_explicitly_disabled_even_on_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIO_ALLOW_SETUP', '0')
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app, client=('127.0.0.1', 12345)) as client:
        response = client.post('/api/auth/setup', json={'username': 'admin', 'password': 'safe-password-123', 'display_name': '管理员'})
        assert response.status_code == 403
        assert client.get('/api/auth/status').json()['needs_setup'] is False
    with app.state.db.transaction() as tx:
        assert tx.all('users') == []
