"""Shipping archives a printed order; its images are deleted after a per-order retention, records stay."""
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_api import png, upload
from backend.tests.test_mixed_stickers import sticker
from backend.tests.test_customer_orders import action, opened, run
from backend.tests.helpers import member, order_items, stored_order
from backend.app.maintenance import purge_due
from backend.app.statistics import summarize

DAY = 86400


def printed(app, c, number, sid, avatar):
    """A submitted order whose print files are ready."""
    o = opened(c, number)
    body = {'avatars': [{'upload_id': avatar, 'template_ids': [], 'sticker_ids': [sid, sid]}]}
    o = action(c, o, 'generate', **body).json()
    run(app)
    o = c.get('/api/customer-orders/'+o['id']).json()
    o = action(c, o, 'submit', slot_ids=[s['id'] for s in o['slots']]).json()
    assert o['state'] == 'submitted'
    return o


def stats(app):
    with app.state.db.transaction() as tx:
        return summarize(tx, tx.all('users')[0], app.state.clock(), days=0, global_scope=True)['summary']


def test_ship_unship_and_tracking_with_retention_fixed_at_shipping(context):
    app, c, clock, _ = context
    sid = sticker(c, 'ONE')['id']
    o = printed(app, c, 'SHIP-1', sid, upload(c)['id'])
    # Print files must exist before shipping.
    assert action(c, o, 'ship').status_code == 409
    app.state.worker.publish(o['id']); o = c.get('/api/customer-orders/'+o['id']).json()
    assert o['delivery_ready']
    # Any staff member ships, with an optional tracking number.
    staff, _ = member(c, app)
    shipped = action(staff, o, 'ship', tracking_number='  SF1234567890 ')
    assert shipped.status_code == 200, shipped.text
    o = shipped.json()
    assert o['state'] == 'shipped' and o['tracking_number'] == 'SF1234567890'
    assert o['purge_at'] == o['shipped_at'] + 15 * DAY and o['purged_at'] is None
    # Still downloadable until deletion; no longer unlockable or repackable.
    assert c.get('/api/customer-orders/'+o['id']+'/download.zip').status_code == 200
    assert action(c, o, 'unlock').status_code == 409 and action(c, o, 'repack').status_code == 409
    # The customer sees shipped, the tracking number, the deletion time and the overview only.
    guest = TestClient(app); guest.post('/api/guest/login', json={'order_number': 'SHIP-1'})
    g = guest.get('/api/guest/order').json()
    assert (g['state'], g['tracking_number'], g['purge_at']) == ('shipped', 'SF1234567890', o['purge_at'])
    assert 'slots' not in g and guest.get(g['preview_url']).status_code == 200
    assert action(staff, o, 'tracking', tracking_number='\x00').status_code == 422
    o = action(staff, o, 'tracking', tracking_number='YT99').json(); assert o['tracking_number'] == 'YT99'
    # Undo by any staff member; the deadline goes away and restarts on the next shipping.
    o = action(staff, o, 'unship').json()
    assert o['state'] == 'submitted' and 'purge_at' not in o and o['delivery_ready']
    assert c.patch('/api/admin/settings', json={'shipped_retention_days': 0}).status_code == 422
    assert c.patch('/api/admin/settings', json={'shipped_retention_days': 3}).json()['shipped_retention_days'] == 3
    assert staff.patch('/api/admin/settings', json={'shipped_retention_days': 9}).status_code == 403
    clock.value += 100
    o = action(c, o, 'ship').json()
    assert o['purge_at'] == clock.value + 3 * DAY and o['tracking_number'] == ''
    # Changing the setting later keeps the deadline already shown to the customer.
    c.patch('/api/admin/settings', json={'shipped_retention_days': 30})
    assert c.get('/api/customer-orders/'+o['id']).json()['purge_at'] == clock.value + 3 * DAY
    assert c.get('/api/customer-orders?state=shipped').json()[0]['id'] == o['id']


def test_purge_deletes_images_after_the_deadline_and_keeps_records(context):
    app, c, clock, provider = context
    sid = sticker(c, 'ONE')['id']
    avatar = upload(c)['id']
    o = printed(app, c, 'SHIP-2', sid, avatar)
    other = printed(app, c, 'SHIP-3', sid, avatar)  # shares the same staff avatar upload
    c.patch('/api/admin/settings', json={'shipped_retention_days': 1})
    app.state.worker.publish(o['id']); app.state.worker.publish(other['id'])
    o = action(c, c.get('/api/customer-orders/'+o['id']).json(), 'ship', tracking_number='SF1').json()
    before = stats(app)
    order = stored_order(app, o)
    with app.state.db.transaction() as tx:
        avatar_asset = tx.get('uploads', avatar)['asset_id']
        mine = [tx.get('assets', i) for i in {i['result_id'] for i in order_items(app, o)} | {a['id'] for a in order['artifacts']}]
        shared_template = order_items(app, o)[0]['template_id']
    assert all(a and (app.state.db.root/'assets'/a['file']).exists() for a in mine)
    staff_media = c.get('/api/customer-orders/'+o['id']).json()['slots'][0]['versions'][0]['preview_url']
    assert c.get(staff_media).status_code == 200
    # Nothing happens before the deadline.
    clock.value = o['purge_at'] - 1
    assert purge_due(app.state.db, clock.value) == 0
    clock.value = o['purge_at']
    assert purge_due(app.state.db, clock.value) == 1
    assert purge_due(app.state.db, clock.value) == 0
    # Files and their records are gone; the avatar another order uses and library images stay.
    assert not any((app.state.db.root/'assets'/a['file']).exists() for a in mine)
    with app.state.db.transaction() as tx:
        assert all(tx.get('assets', a['id']) is None for a in mine)
        assert tx.get('assets', avatar_asset) and tx.get('uploads', avatar) and tx.get('assets', shared_template)
        assert not tx.all('cleanup_files')
    assert c.get(staff_media).status_code == 404
    # Order, items and statistics remain; staff and the customer see when images were deleted.
    o = c.get('/api/customer-orders/'+o['id']).json()
    assert o['purged_at'] == clock.value and o['slots'] == [] and o['avatars'] == [] and o['preview_url'] is None
    assert not o['delivery_ready'] and o['tracking_number'] == 'SF1'
    assert len(order_items(app, o)) == 1 and stats(app) == before
    guest = TestClient(app); guest.post('/api/guest/login', json={'order_number': 'SHIP-2'})
    g = guest.get('/api/guest/order').json()
    assert (g['state'], g['purged_at'], g['preview_url'], g['slots']) == ('shipped', clock.value, None, [])
    assert c.get('/api/customer-orders/'+o['id']+'/download.zip').status_code == 409
    assert action(c, o, 'unship').status_code == 409
    assert action(c, o, 'tracking', tracking_number='SF2').json()['tracking_number'] == 'SF2'
    # The other order is untouched.
    other = c.get('/api/customer-orders/'+other['id']).json()
    assert other['state'] == 'submitted' and other['delivery_ready'] and other['avatars']
    assert c.get(other['avatars'][0]['preview_url']).status_code == 200
    assert c.get(other['slots'][0]['versions'][0]['preview_url']).status_code == 200


def test_unshipped_and_refunded_orders(context):
    app, c, clock, _ = context
    sid = sticker(c, 'ONE')['id']
    o = printed(app, c, 'SHIP-4', sid, upload(c)['id'])
    c.patch('/api/admin/settings', json={'shipped_retention_days': 1})
    app.state.worker.publish(o['id'])
    o = action(c, c.get('/api/customer-orders/'+o['id']).json(), 'ship').json()
    o = action(c, o, 'unship').json()
    clock.value += 2 * DAY
    assert purge_due(app.state.db, clock.value) == 0
    # Cancelled after shipping (for example a refund): images still go at the shipped deadline.
    o = action(c, action(c, o, 'ship').json(), 'cancel').json()
    assert o['state'] == 'cancelled'
    clock.value = stored_order(app, o)['purge_at']
    assert purge_due(app.state.db, clock.value) == 1
    restored = action(c, c.get('/api/customer-orders/'+o['id']).json(), 'restore').json()
    assert restored['state'] == 'shipped' and restored['purged_at'] == clock.value
