import io
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from PIL import Image

from backend.tests.test_api import app, client, upload, png, template, order


def test_preview_dimensions_alpha_etag_and_unchanged_original(client):
    value = upload(client, png(size=(1600, 1200)))
    original = client.get(value['url']).content
    url = value['url'] + '/preview?size=320'
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/webp'
    image = Image.open(io.BytesIO(response.content))
    assert image.size == (320, 240)
    expected = Image.open(io.BytesIO(original))
    expected.thumbnail((320, 320), Image.Resampling.LANCZOS)
    assert image.getchannel('A').tobytes() == expected.getchannel('A').tobytes()
    assert response.headers['cache-control'] == 'private, no-cache'
    assert response.headers['vary'] == 'Cookie'
    cached = client.get(url, headers={'If-None-Match': response.headers['etag']})
    assert cached.status_code == 304 and not cached.content
    assert client.get(value['url']).content == original
    assert client.get(value['url']).headers['cache-control'] == 'no-store'
    assert client.get(value['url'] + '/preview?size=321').status_code == 422
    large = Image.open(io.BytesIO(client.get(value['url'] + '/preview?size=1280').content))
    assert large.size == (1280, 960)
    small = upload(client)
    assert Image.open(io.BytesIO(client.get(small['url']+'/preview').content)).size == (32, 32)


def test_cache_hit_and_conditional_request_still_require_permission(client, app):
    value = upload(client)
    url = value['url'] + '/preview'
    response = client.get(url)
    assert response.status_code == 200
    headers = {'If-None-Match': response.headers['etag']}
    invite = client.post('/api/admin/invites').json()['code']
    with TestClient(app) as other:
        assert other.get(url, headers=headers).status_code == 401
        other.post('/api/auth/register', json={'invite': invite, 'username': 'staff', 'password': 'safe-password-123', 'display_name': '员工'})
        assert other.get(url, headers=headers).status_code == 304  # same organization
    client.post('/api/auth/logout')
    assert client.get(url, headers=headers).status_code == 401


def test_order_cleanup_removes_all_cached_variants_preserves_template_cache(client, app):
    value, _ = order(client)
    t = client.get('/api/templates').json()[0]['images'][0]
    for url in [value['avatar_url'], t['url']]:
        for size in ([320] if url == value['avatar_url'] else [320, 1280]):
            assert client.get(url+f'/preview?size={size}').status_code == 200
    root = app.state.db.root/'preview-cache'
    assert len(list(root.rglob('*.webp'))) == 3
    request = {'before':'2026-01-01T00:00:00Z'}
    # Use a future cutoff regardless of the clock in the basic API fixture.
    request['before'] = '2099-01-01T00:00:00Z'
    plan = client.post('/api/admin/cleanup/preview', json=request).json()
    assert plan['preview_cache_files'] == 1
    assert plan['preview_cache_bytes'] > 0
    # A cached file can appear after preview; cleanup must still remove it.
    assert client.get(value['avatar_url']+'/preview?size=1280').status_code == 200
    result = client.post('/api/admin/cleanup', json={**request, 'preview_token': plan['preview_token'], 'confirmed': True})
    assert result.status_code == 200 and result.json()['pending_files'] == 0
    assert not (root/value['avatar_url'].split('/')[-1]).exists()
    assert len(list((root/t['id']).glob('*.webp'))) == 2
    assert client.get(value['avatar_url']+'/preview').status_code == 404
    assert client.get(t['url']+'/preview').status_code == 200


def test_preview_cache_lru_budget_restart_and_encoding_once(client, app, monkeypatch):
    from backend.app.previews import PreviewCache
    cache = app.state.preview_cache
    assets = [upload(client, png((i*40, 60, 80, 180), (80, 80))) for i in range(3)]
    first = client.get(assets[0]['url']+'/preview')
    assert first.status_code == 200
    entry = next((cache.root/assets[0]['url'].split('/')[-1]).glob('*.webp'))
    assert entry.stat().st_mode & 0o777 == 0o600
    old_mtime = entry.stat().st_mtime
    os.utime(entry, (1, 1))
    assert client.get(assets[0]['url']+'/preview').content == first.content
    assert entry.stat().st_mtime > old_mtime
    # Restart uses existing encoded data, including concurrent requests.
    app.state.preview_cache = PreviewCache(app.state.db)
    def forbidden(*a, **kw): raise AssertionError('cache hit must not encode')
    monkeypatch.setattr(app.state.preview_cache, '_encode', forbidden)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.get(assets[0]['url']+'/preview'), range(4)))
    assert all(r.content == first.content for r in responses)
    app.state.preview_cache = cache
    cache.max_bytes = len(first.content)*2
    os.utime(entry, (1, 1))
    for asset in assets[1:]:
        assert client.get(asset['url']+'/preview').status_code == 200
    assert sum(p.stat().st_size for p in cache.root.rglob('*') if p.is_file()) <= cache.max_bytes
    assert not entry.exists()


def test_preview_deleted_during_encoding_cannot_recreate_cache(client, app, monkeypatch):
    value = upload(client)
    cache = app.state.preview_cache
    native = cache._encode
    def deleting(*args):
        result = native(*args)
        with app.state.db.transaction() as tx:
            tx.delete('assets', value['url'].split('/')[-1])
        return result
    monkeypatch.setattr(cache, '_encode', deleting)
    assert client.get(value['url']+'/preview').status_code == 404
    assert not list(cache.root.rglob('*.webp'))


def test_cache_deletion_failure_is_retryable(client, app, monkeypatch):
    from pathlib import Path
    value, _ = order(client)
    assert client.get(value['avatar_url']+'/preview').status_code == 200
    path = next((app.state.preview_cache.root/value['avatar_url'].split('/')[-1]).glob('*.webp'))
    native = Path.unlink
    def blocked(p, *args, **kwargs):
        if p == path: raise PermissionError('test')
        return native(p, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', blocked)
    request = {'before': '2099-01-01T00:00:00Z'}
    plan = client.post('/api/admin/cleanup/preview', json=request).json()
    result = client.post('/api/admin/cleanup', json={**request, 'preview_token': plan['preview_token'], 'confirmed': True})
    assert result.json()['pending_files'] == 1
    assert client.get(value['avatar_url']+'/preview').status_code == 404
    monkeypatch.setattr(Path, 'unlink', native)
    assert client.post('/api/admin/cleanup/retry').json()['pending_files'] == 0
    assert not path.exists()


def test_concurrent_cold_requests_encode_once_and_low_disk_does_not_store(client, app, monkeypatch):
    from collections import namedtuple
    import backend.app.previews as previews
    value = upload(client, png(size=(512, 512)))
    native = app.state.preview_cache._encode
    calls = []
    def counting(*args):
        calls.append(1)
        return native(*args)
    monkeypatch.setattr(app.state.preview_cache, '_encode', counting)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.get(value['url']+'/preview'), range(6)))
    assert all(r.status_code == 200 and r.content == responses[0].content for r in responses)
    assert len(calls) == 1
    low = upload(client)
    Usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(previews.shutil, 'disk_usage', lambda _: Usage(1000, 999, 1))
    response = client.get(low['url']+'/preview')
    assert response.status_code == 200 and response.headers['content-type'] == 'image/webp'
    assert not (app.state.preview_cache.root/low['url'].split('/')[-1]).exists()


def test_white_overview_and_new_asset_version_have_distinct_cached_previews(client, app):
    from backend.app.storage import save_asset
    owner = client.get('/api/auth/me').json()['id']
    images = []
    with app.state.db.transaction() as tx:
        for color in ['white', 'red']:
            data = io.BytesIO()
            Image.new('RGB', (1024, 768), color).save(data, 'PNG')
            images.append(save_asset(app.state.db, tx, data.getvalue(), owner, 'overview'))
    first = client.get(images[0]['url']+'/preview')
    assert Image.open(io.BytesIO(first.content)).convert('RGB').getpixel((0, 0)) == (255, 255, 255)
    second = client.get(images[1]['url']+'/preview', headers={'If-None-Match':first.headers['etag']})
    assert second.status_code == 200
    assert second.headers['etag'] != first.headers['etag'] and second.content != first.content
