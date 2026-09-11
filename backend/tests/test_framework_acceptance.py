"""Cross-subsystem acceptance: real HTTP authorization, media and transactions."""
import concurrent.futures
import hashlib
import json

from fastapi.testclient import TestClient

from backend.tests.test_worker import context
from backend.tests.test_customer_orders import action, generate, opened, run
from backend.tests.test_mixed_stickers import sticker


def test_guest_cannot_read_any_backend_original_or_other_order_media(context):
    app, staff, _, _ = context
    first = generate(staff, opened(staff, 'PRIVATE-A'), sticker(staff, 'PRIVACY')['id'])
    run(app)
    second = opened(staff, 'PRIVATE-B')
    guest_a, guest_b = TestClient(app), TestClient(app)
    assert guest_a.post('/api/guest/login', json={'order_number':first['order_number']}).status_code == 200
    assert guest_b.post('/api/guest/login', json={'order_number':second['order_number']}).status_code == 200
    data = guest_a.get('/api/guest/order').json()
    assert all(forbidden not in json.dumps(data) for forbidden in ['private note', '/api/assets/', 'fal_request', 'raw_result'])
    link = data['slots'][0]['versions'][0]['preview_url']
    assert guest_a.get(link).status_code == 200
    assert guest_b.get(link).status_code == 404
    with app.state.db.transaction() as tx:
        assets = tx.all('assets')
    for asset in assets:
        for suffix in ('', '/preview?size=1280'):
            assert guest_a.get('/api/assets/'+asset['id']+suffix).status_code == 401
    for path in ('/api/orders', '/api/customer-orders', '/api/admin/settings', '/api/admin/users', '/api/stickers', '/api/templates'):
        assert guest_a.get(path).status_code == 401


def test_duplicate_parallel_rerun_allocates_one_task_and_one_reservation(context):
    app, staff, _, _ = context
    order = generate(staff, opened(staff, 'RACE'), sticker(staff, 'RACE')['id'])
    run(app)
    order = staff.get('/api/customer-orders/'+order['id']).json()
    path = '/api/customer-orders/'+order['id']+'/slots/'+order['slots'][0]['id']+'/rerun'
    body = {'client_token':'identical-network-retry','expected_version':order['version']}
    cookies = dict(staff.cookies)
    def send():
        with TestClient(app) as client:
            client.cookies.update(cookies)
            return client.post(path, json=body)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: send(), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    result = staff.get('/api/customer-orders/'+order['id']).json()
    assert result['slots'][0]['reruns_reserved'] == 1
    with app.state.db.transaction() as tx:
        assert len([i for i in tx.all('items') if i['order_id'] == order['id']]) == 2


def test_watermark_batch_changes_no_originals_and_revokes_old_preview_links(context):
    app, staff, _, provider = context
    order = generate(staff, opened(staff, 'WATERMARK'), sticker(staff, 'MARK')['id'])
    run(app)
    guest = TestClient(app)
    guest.post('/api/guest/login', json={'order_number':order['order_number']})
    before = guest.get('/api/guest/order').json()
    link = before['slots'][0]['versions'][0]['preview_url']
    pixels_before = guest.get(link).content
    with app.state.db.transaction() as tx:
        original_hashes = {a['id']:a['sha256'] for a in tx.all('assets')}
    calls = len(provider.calls)
    assert staff.patch('/api/account', json={'watermark':'TEST STORE NEW WATERMARK'}).status_code == 200
    preview = staff.post('/api/customer-orders/watermarks/preview', json={'ids':[order['id']]}).json()
    assert preview['orders'][0]['watermark'] == 'TEST STORE NEW WATERMARK'
    result = staff.post('/api/customer-orders/watermarks', json={'ids':[order['id']], 'preview_token':preview['preview_token'], 'client_token':'apply-watermark'})
    assert result.status_code == 200, result.text
    assert guest.get(link).status_code == 404
    after = guest.get('/api/guest/order').json()
    pixels_after = guest.get(after['slots'][0]['versions'][0]['preview_url']).content
    assert hashlib.sha256(pixels_before).digest() != hashlib.sha256(pixels_after).digest()
    assert len(provider.calls) == calls
    with app.state.db.transaction() as tx:
        assert all(tx.get('assets', identifier)['sha256'] == sha for identifier, sha in original_hashes.items())


def test_submitted_guest_cannot_reopen_single_image_by_guessing_new_revision(context):
    app, staff, _, _ = context
    order = generate(staff, opened(staff, 'LOCKED'), sticker(staff, 'LOCKED')['id'])
    run(app)
    guest = TestClient(app)
    guest.post('/api/guest/login', json={'order_number':order['order_number']})
    before = guest.get('/api/guest/order').json()
    link = before['slots'][0]['versions'][0]['preview_url']
    order = staff.get('/api/customer-orders/'+order['id']).json()
    result = action(staff, order, 'submit', slot_ids=[s['id'] for s in order['slots']])
    assert result.status_code == 200, result.text
    app.state.worker.publish(order['id'])
    locked = guest.get('/api/guest/order').json()
    assert not {'slots', 'avatars', 'notes', 'watermark', 'print_settings'} & locked.keys()
    assert guest.get(link).status_code == 404
    with app.state.db.transaction() as tx:
        current = tx.get('orders', order['id'])
    guessed = link.split('?')[0] + '?v=' + str(current['media_version'])
    assert guest.get(guessed).status_code == 404
    assert guest.get(locked['preview_url']).status_code == 200
