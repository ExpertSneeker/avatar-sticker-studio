"""Private browser caching must never bypass live customer-media authorization."""
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
    # Even after the server derivative cache is lost, 304 requires no image IO.
    guest_media._cache.clear()
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


def test_watermark_update_invalidates_old_url_and_validator(context):
    _, staff, guest, order, link = preview(context)
    headers = {'If-None-Match': guest.get(link).headers['etag']}
    assert staff.patch('/api/account', json={'watermark': 'NEW CACHE WATERMARK'}).status_code == 200
    proposal = staff.post('/api/customer-orders/watermarks/preview', json={'ids': [order['id']]}).json()
    result = staff.post('/api/customer-orders/watermarks', json={'ids': [order['id']], 'preview_token': proposal['preview_token'], 'client_token': 'cache-watermark'})
    assert result.status_code == 200
    assert guest.get(link, headers=headers).status_code == 404
    updated = guest.get('/api/guest/order').json()['slots'][0]['versions'][0]['preview_url']
    response = guest.get(updated, headers=headers)
    assert response.status_code == 200 and response.headers['etag'] != headers['If-None-Match']


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
