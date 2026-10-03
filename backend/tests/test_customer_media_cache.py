"""Private browser caching must never bypass live customer-media authorization."""
import shutil
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_customer_orders import opened, generate, run, action
from backend.tests.test_mixed_stickers import sticker


def preview(context, mode='guest'):
    app, staff, clock, _ = context
    order = generate(staff, opened(staff), sticker(staff, 'CACHE')['id'])
    run(app)
    order = staff.get('/api/customer-orders/' + order['id']).json()
    client = staff
    if mode == 'guest':
        client = TestClient(app)
        assert client.post('/api/guest/login', json={'order_number': order['order_number']}).status_code == 200
        data = client.get('/api/guest/order').json()
    else:
        data = order
    return app, staff, client, order, data['slots'][0]['versions'][0]['preview_url']


@pytest.mark.parametrize('mode', ['guest', 'staff'])
def test_browser_cache_revalidates_without_reading_or_rendering_images(context, monkeypatch, mode):
    from backend.app import guest_media
    app, _, client, _, link = preview(context, mode)
    first = client.get(link)
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'private, no-cache'
    assert first.headers['vary'] == 'Cookie'
    etag = first.headers['etag']
    assert etag.startswith('W/"')
    # Even after the server derivative caches are lost, 304 requires no image IO.
    app.state.media_memory.clear()
    shutil.rmtree(app.state.media_cache.root)
    def unexpected(*args):
        pytest.fail('Conditional cache hit read or rendered an image')
    monkeypatch.setattr(guest_media, 'render', unexpected)
    monkeypatch.setattr(guest_media, 'asset_bytes', unexpected)
    for match in (etag, etag.removeprefix('W/'), '"other", ' + etag, '*'):
        response = client.get(link, headers={'If-None-Match': match})
        assert response.status_code == 304 and response.content == b''
        assert response.headers['etag'] == etag
        assert response.headers['cache-control'] == 'private, no-cache'
        assert response.headers['vary'] == 'Cookie'


def test_nonmatching_and_different_size_validators_transfer_the_correct_image(context):
    _, _, client, _, link = preview(context)
    first = client.get(link)
    etag = first.headers['etag']
    changed_size = client.get(link + '&size=320', headers={'If-None-Match': etag})
    assert changed_size.status_code == 200 and changed_size.headers['etag'] != etag
    response = client.get(link, headers={'If-None-Match': '"unrelated"'})
    assert response.status_code == 200 and response.content == first.content


@pytest.mark.parametrize('mode', ['guest', 'staff'])
def test_conditional_requests_cannot_bypass_logout_or_cancel(context, mode):
    app, staff, client, order, link = preview(context, mode)
    headers = {'If-None-Match': client.get(link).headers['etag']}
    assert action(staff, order, 'cancel').status_code == 200
    rejected = client.get(link, headers=headers)
    assert rejected.status_code == 404 and rejected.headers['cache-control'] == 'no-store'
    assert client.post('/api/' + ('guest' if mode == 'guest' else 'auth') + '/logout').status_code == 200
    assert client.get(link, headers=headers).status_code == 401


def test_guest_conditional_requests_reject_other_orders_and_expired_sessions(context):
    app, staff, guest, _, link = preview(context)
    headers = {'If-None-Match': guest.get(link).headers['etag']}
    assert TestClient(app).get(link, headers=headers).status_code == 401
    other = opened(staff, 'OTHER-CACHE')
    assert guest.post('/api/guest/login', json={'order_number': other['order_number']}).status_code == 200
    assert guest.get(link, headers=headers).status_code == 404
    context[2].value += 7 * 86400 + 1
    assert guest.get(link, headers=headers).status_code == 401


@pytest.mark.parametrize('mode', ['guest', 'staff'])
def test_conditional_requests_reject_disabled_access(context, mode):
    app, staff, client, order, link = preview(context, mode)
    headers = {'If-None-Match': client.get(link).headers['etag']}
    with app.state.db.transaction() as tx:
        kind, id = ('organizations', order['organization_id']) if mode == 'guest' else ('users', order['owner'])
        record = tx.get(kind, id)
        record['active'] = False
        tx.put(kind, record)
    assert client.get(link, headers=headers).status_code == 401


def test_watermark_update_keeps_the_link_but_changes_content_and_validator(context):
    _, staff, guest, order, link = preview(context)
    first = guest.get(link)
    headers = {'If-None-Match': first.headers['etag']}
    assert staff.patch('/api/account', json={'watermark': 'NEW CACHE WATERMARK'}).status_code == 200
    proposal = staff.post('/api/customer-orders/watermarks/preview', json={'ids': [order['id']]}).json()
    result = staff.post('/api/customer-orders/watermarks', json={'ids': [order['id']], 'preview_token': proposal['preview_token'], 'client_token': 'cache-watermark'})
    assert result.status_code == 200
    # Only the watermark fingerprint in the link changes; the content key changes the validator.
    updated = guest.get('/api/guest/order').json()['slots'][0]['versions'][0]['preview_url']
    assert updated != link and updated.split('?')[0] == link.split('?')[0]
    for url in (link, updated):
        response = guest.get(url, headers=headers)
        assert response.status_code == 200 and response.headers['etag'] != headers['If-None-Match']
        assert response.content != first.content


def test_cross_organization_staff_cannot_revalidate_customer_media(context):
    app, staff, _, _, link = preview(context, 'staff')
    headers = {'If-None-Match': staff.get(link).headers['etag']}
    result = staff.post('/api/admin/organizations', json={'name': 'foreign', 'admin_username': 'foreign', 'admin_display_name': 'foreign'})
    assert result.status_code == 200
    other = TestClient(app)
    assert other.post('/api/auth/login', json={'username': 'foreign', 'password': result.json()['temporary_password']}).status_code == 200
    assert other.get(link, headers=headers).status_code == 404


def test_cancel_between_conditional_validation_and_response_rejects_304(context, monkeypatch):
    app, staff, guest, order, link = preview(context)
    headers = {'If-None-Match': guest.get(link).headers['etag']}
    read = app.state.db.read
    cancelled = False
    def interrupted(fn):
        nonlocal cancelled
        result = read(fn)
        if not cancelled:
            cancelled = True
            assert action(staff, order, 'cancel').status_code == 200
        return result
    monkeypatch.setattr(app.state.db, 'read', interrupted)
    assert guest.get(link, headers=headers).status_code == 404


def test_requested_sizes_snap_to_fixed_tiers_and_share_one_render(context, monkeypatch):
    import io
    from PIL import Image
    from backend.app import guest_media
    app, _, client, _, link = preview(context)
    default = client.get(link)
    assert client.get(link + '&size=640').headers['etag'] == default.headers['etag']
    renders = []
    original = guest_media.render
    monkeypatch.setattr(guest_media, 'render', lambda *args: renders.append(args[2]) or original(*args))
    app.state.media_memory.clear()
    shutil.rmtree(app.state.media_cache.root)
    for requested, expected in ((1, 160), (161, 320), (300, 320), (320, 320), (321, 640), (700, 1024), (5000, 1024)):
        response = client.get(link + f'&size={requested}')
        assert response.status_code == 200
        assert max(Image.open(io.BytesIO(response.content)).size) == expected
        assert response.headers['etag'] == client.get(link + f'&size={expected}').headers['etag']
    assert sorted(renders) == [160, 320, 640, 1024]


def test_thumbnail_tiers_keep_the_640_watermark_appearance():
    import io
    from PIL import Image, ImageChops, ImageStat
    from backend.app import guest_media
    source = Image.new('RGBA', (1024, 1024), (240, 170, 120, 255))
    data = io.BytesIO(); source.save(data, 'PNG'); data = data.getvalue()
    mark = '贴纸小店·仅供预览'
    assert guest_media.pipeline(640) == guest_media.pipeline(1024) == guest_media.PIPELINE
    assert guest_media.pipeline(160) == guest_media.pipeline(320) != guest_media.PIPELINE
    for size in (160, 320):
        reference = guest_media.watermarked(data, mark, 640).convert('RGB')
        reference.thumbnail((size, size), Image.Resampling.LANCZOS)
        direct = guest_media.watermarked(data, mark, size).convert('RGB')
        actual = Image.open(io.BytesIO(guest_media.render(data, mark, size))).convert('RGB')
        difference = lambda image: max(ImageStat.Stat(ImageChops.difference(actual, image)).mean)
        assert actual.size == (size, size)
        # Same watermark as the 640 preview, not the heavier small-size layout.
        assert difference(reference) < 3 and difference(direct) > 6


def test_render_cache_is_byte_bounded_lru():
    from backend.app.guest_media import _CACHE_BYTES, _ByteLRU
    assert _CACHE_BYTES == 256 * 1024 * 1024
    cache = _ByteLRU(10)
    cache.put('a', b'1234'); cache.put('b', b'1234')
    cache.move_to_end('a')
    cache.put('b', b'12345')  # replacing an entry counts only its new size
    assert cache.bytes == 9 and list(cache) == ['a', 'b']
    cache.put('c', b'123')  # evicts least recently used first
    assert list(cache) == ['b', 'c'] and cache.bytes == 8
    cache.put('d', b'12345678901')  # an entry larger than the limit is not kept
    assert not cache and cache.bytes == 0
    cache.put('e', b'1'); cache.clear()
    assert cache.bytes == 0
