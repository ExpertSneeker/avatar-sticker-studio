"""Indexed lookups must return exactly what the former full scans returned."""
from backend.app.db import INDEXED_FIELDS, Database
from backend.tests.test_customer_orders import generate, opened, run
from backend.tests.test_mixed_stickers import sticker
from backend.tests.test_worker import context  # noqa: F401  (fixture)


def test_indexes_exist_and_are_used(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        names = {row[0] for row in tx.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {'records_' + field for field in INDEXED_FIELDS} <= names
        plan = ' '.join(row[3] for row in tx.conn.execute(
            "EXPLAIN QUERY PLAN SELECT rowid, doc FROM records WHERE kind=? AND (json_extract(doc,'$.order_number') IN (?))", ('orders', 'x')))
        assert 'records_order_number' in plan
    Database(tmp_path)  # Reopening keeps the same schema without errors.


def test_where_and_find_match_full_scan_in_rowid_order(tmp_path):
    db = Database(tmp_path)
    values = ['queued', 'running', None, 'failed', 'queued', True, 1, 'running']
    with db.transaction() as tx:
        for n, value in enumerate(values):
            doc = {'id': f'z{9 - n}', 'n': n}  # ids deliberately sort against insertion order
            if value is not None:
                doc['status'] = value
            doc['remote_reserved'] = n % 3 == 0
            tx.put('items', doc)
        tx.put('orders', {'id': 'other', 'status': 'queued'})
        scan = tx.all('items')
        assert tx.where('items', 'status', 'queued', 'running') == [d for d in scan if d.get('status') in ('queued', 'running')]
        assert tx.where('items', 'remote_reserved', True) == [d for d in scan if d['remote_reserved']]
        claim = tx.find('items', ("json_extract(doc,'$.status') IN ('queued','running')", ()), ("json_extract(doc,'$.remote_reserved') = 1", ()))
        assert claim == [d for d in scan if d.get('status') in ('queued', 'running') or d['remote_reserved']]
        assert tx.count('items') == len(scan) == len(values)


def test_summary_list_omits_only_avatars_and_slots(context):
    app, c, _, _ = context
    order = generate(c, opened(c), sticker(c, 'ONE')['id'])
    run(app)
    full = c.get('/api/customer-orders').json()[0]
    summary = c.get('/api/customer-orders?summary=1').json()[0]
    assert full['slots'] and full['avatars']
    assert summary == {k: v for k, v in full.items() if k not in {'avatars', 'slots'}}
    assert c.get('/api/customer-orders/' + order['id']).json() == full


def test_guest_login_by_indexed_order_number(context):
    app, c, _, _ = context
    opened(c, 'FIRST')
    target = opened(c, 'SECOND')
    guest = type(c)(app)
    response = guest.post('/api/guest/login', json={'order_number': ' SECOND '})
    assert response.status_code == 200 and response.json()['id'] == target['id']
    assert guest.post('/api/guest/login', json={'order_number': 'SECON'}).status_code == 401
