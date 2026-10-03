"""Persistent watermarked media cache: content sharing, restart survival, retention, cleanup and pregeneration."""
import io
import os
import time
import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.tests.test_worker import context
from backend.tests.test_customer_orders import opened, generate, run, action
from backend.tests.test_mixed_stickers import sticker


def guest(app, order):
    client = TestClient(app)
    assert client.post('/api/guest/login', json={'order_number': order['order_number']}).status_code == 200
    return client, {**client.get('/api/guest/order').json(), 'library': client.get('/api/guest/library').json()}


def library_link(data, code):
    return next(s['preview_url'] for s in data['library']['stickers'] if s['code'] == code)


def cached(app, scope):
    return sorted(p for p in (app.state.media_cache.root / scope).rglob('*.webp'))


def forbid_render(monkeypatch):
    from backend.app import guest_media
    def unexpected(*args):
        pytest.fail('expected a cached image, not a render')
    monkeypatch.setattr(guest_media, 'render', unexpected)


def test_library_renders_are_shared_across_orders_and_survive_restart(context, monkeypatch, tmp_path):
    app, staff, _, _ = context
    sticker(staff, 'SHARE')
    first, data = guest(app, opened(staff, 'SHARE-1'))
    link = library_link(data, 'SHARE')
    assert link.split('?')[1].startswith('m=')
    original = first.get(link + '&size=320')
    assert original.status_code == 200
    [path] = cached(app, 'library')
    assert path.parent.name == link.split('?')[0].rsplit('/', 1)[1] and path.name.split('-')[1] == '320'
    # Another order with the same watermark reuses the render (memory and disk).
    second, data = guest(app, opened(staff, 'SHARE-2'))
    forbid_render(monkeypatch)
    again = second.get(library_link(data, 'SHARE') + '&size=320')
    assert again.content == original.content and again.headers['etag'] == original.headers['etag']
    # A new process (empty memory) is served from disk.
    restarted = create_app(tmp_path, start_worker=False)
    with TestClient(restarted) as client:
        assert client.post('/api/guest/login', json={'order_number': 'SHARE-1'}).status_code == 200
        response = client.get(link + '&size=320')
        assert response.status_code == 200 and response.content == original.content


def test_customer_images_are_scoped_by_organization_and_library_auth_uses_the_index(context):
    app, staff, _, _ = context
    order = generate(staff, opened(staff), sticker(staff, 'SCOPE')['id']); run(app)
    client, data = guest(app, order)
    assert client.get(data['slots'][0]['versions'][0]['preview_url']).status_code == 200
    [path] = cached(app, 'customer')
    assert path.parent.parent.name == order['organization_id']
    with app.state.db.transaction() as tx:
        plan = ' '.join(str(row) for row in tx.conn.execute(
            "EXPLAIN QUERY PLAN SELECT doc FROM records WHERE kind='stickers' AND (json_extract(doc,'$.image.id') = ?)", ('x',)))
    assert 'records_image_id' in plan


def test_deleted_library_stickers_are_rejected(context):
    app, staff, _, _ = context
    value = sticker(staff, 'GONE')
    client, data = guest(app, opened(staff))
    link = library_link(data, 'GONE')
    assert client.get(link).status_code == 200
    assert staff.delete('/api/stickers/' + value['id']).status_code == 200
    assert client.get(link).status_code == 404


def test_organization_admin_sets_retention_and_sweep_applies_it(context):
    app, staff, _, _ = context
    assert staff.get('/api/organization/settings').json() == {'media_cache_days': 15, 'default_media_cache_days': 15}
    for invalid in (0, 366):
        assert staff.patch('/api/organization/settings', json={'media_cache_days': invalid}).status_code == 422
    assert staff.patch('/api/organization/settings', json={'media_cache_days': 3}).json()['media_cache_days'] == 3
    order = generate(staff, opened(staff), sticker(staff, 'KEEP')['id']); run(app)
    client, data = guest(app, order)
    client.get(data['slots'][0]['versions'][0]['preview_url'])
    client.get(library_link(data, 'KEEP'))
    [customer] = cached(app, 'customer')
    [library] = cached(app, 'library')
    old = time.time() - 4 * 86400
    os.utime(customer, (old, old)); os.utime(library, (old, old))
    assert app.state.media_cache.sweep() == 1
    # Customer images expire after the organization's days; library images stay while in use.
    assert not customer.exists() and library.exists()


def test_settings_are_admin_only_and_scoped_to_the_own_organization(context):
    app, staff, _, _ = context
    created = staff.post('/api/admin/organizations', json={'name': 'other', 'admin_username': 'other', 'admin_display_name': 'other'}).json()
    other = TestClient(app)
    assert other.post('/api/auth/login', json={'username': 'other', 'password': created['temporary_password']}).status_code == 200
    assert other.patch('/api/organization/settings', json={'media_cache_days': 30}).status_code == 200
    assert staff.get('/api/organization/settings').json()['media_cache_days'] == 15
    member = other.post('/api/admin/users', json={'username': 'member', 'display_name': 'member'})
    assert member.status_code == 200, member.text
    plain = TestClient(app)
    assert plain.post('/api/auth/login', json={'username': 'member', 'password': member.json()['temporary_password']}).status_code == 200
    assert plain.get('/api/organization/settings').status_code == 403
    assert TestClient(app).get('/api/organization/settings').status_code == 401


def test_sweep_drops_unused_watermarks_and_deleted_stickers(context):
    app, staff, _, _ = context
    value = sticker(staff, 'MARKS')
    client, data = guest(app, opened(staff))
    link = library_link(data, 'MARKS')
    client.get(link)
    [path] = cached(app, 'library')
    assert app.state.media_cache.sweep() == 0
    # The order's watermark stays in use while the order is open.
    assert staff.patch('/api/account', json={'watermark': 'ANOTHER'}).status_code == 200
    assert app.state.media_cache.sweep() == 0 and path.exists()
    order = staff.get('/api/customer-orders/' + data['id']).json()
    assert action(staff, order, 'cancel').status_code == 200
    assert app.state.media_cache.sweep() == 1 and not path.exists()
    staff.patch('/api/account', json={'watermark': ''})
    restored = action(staff, staff.get('/api/customer-orders/' + data['id']).json(), 'restore')
    assert restored.status_code == 200
    # A memory hit restores the swept disk copy.
    assert client.get(link).status_code == 200
    assert cached(app, 'library')
    assert staff.delete('/api/stickers/' + value['id']).status_code == 200
    app.state.media_cache.sweep()
    assert not cached(app, 'library')


def test_durable_cleanup_removes_media_cache_of_deleted_assets(context):
    from backend.app.maintenance import drain_cleanup, stage_cleanup
    app, staff, _, _ = context
    order = generate(staff, opened(staff), sticker(staff, 'CLEAN')['id']); run(app)
    client, data = guest(app, order)
    client.get(data['slots'][0]['versions'][0]['preview_url'])
    [path] = cached(app, 'customer')
    asset_id = path.parent.name
    files = app.state.media_cache.files_for([asset_id])
    assert files == [path]
    with app.state.db.transaction() as tx:
        stage_cleanup(tx, {}, ['media-cache/' + asset_id])
    assert drain_cleanup(app.state.db) == 0
    assert not path.parent.exists()


def test_pregeneration_matches_on_demand_renders_and_is_idempotent(context, monkeypatch):
    from backend.app import guest_media
    from backend.app.media_cache import MediaWarmer
    app, staff, _, _ = context
    sticker(staff, 'WARM')
    order = generate(staff, opened(staff), sticker(staff, 'WARM-2')['id']); run(app)
    warmer = MediaWarmer(app.state.db, app.state.media_cache, pause=0)
    warmer.run_once()
    # Two stickers x one watermark x three tiers, plus the open order's avatar and result at 640.
    assert len(cached(app, 'library')) == 6 and len(cached(app, 'customer')) == 2
    assert warmer.status['generated'] == 8 and warmer.status['pending'] == 0
    warmer.run_once()
    assert warmer.status['generated'] == 8
    client, data = guest(app, order)
    forbid_render(monkeypatch)
    for size in (160, 320, 640):
        response = client.get(library_link(data, 'WARM') + f'&size={size}')
        assert response.status_code == 200
    assert client.get(data['slots'][0]['versions'][0]['preview_url']).status_code == 200
    monkeypatch.undo()
    with app.state.db.transaction() as tx:
        asset = tx.get('assets', library_link(data, 'WARM').split('?')[0].rsplit('/', 1)[1])
    from backend.app.storage import asset_bytes
    source = asset_bytes(app.state.db, asset)
    assert guest_media.render_tiers(source, order['watermark'], (160, 320, 640)) == {s: guest_media.render(source, order['watermark'], s) for s in (160, 320, 640)}


def test_storage_stats_report_watermark_and_customer_cache_separately(context):
    app, staff, _, _ = context
    order = generate(staff, opened(staff), sticker(staff, 'STATS')['id']); run(app)
    client, data = guest(app, order)
    client.get(data['slots'][0]['versions'][0]['preview_url'])
    client.get(library_link(data, 'STATS'))
    media = staff.get('/api/admin/storage').json()['media_cache']
    assert media['library']['files'] == 1 and media['customer']['files'] == 1
    assert media['library']['bytes'] > 0 and media['customer']['bytes'] > 0
    assert media['pregeneration']['running'] is False
