"""Single-order migration is transactional, strict, and preserves provider history."""
import json
import sqlite3
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.app.db import Database
from backend.app.storage import save_asset


def snapshot(db):
    with sqlite3.connect(db.path) as conn:
        return {(kind, key): json.loads(doc) for kind, key, doc in conn.execute('SELECT kind,id,doc FROM records')}


def legacy_fixture(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        org = tx.all('organizations')[0]['id']
        tx.put('users', {'id': 'u', 'organization_id': org, 'role': 'org_admin', 'username': 'synthetic',
                         'active': True, 'credits': {'available': 3, 'frozen': 2, 'spent': 7, 'version': 5}})
        raw = save_asset(db, tx, b'synthetic-raw-image', 'u', 'raw_result', order_id='o')
        tx.put('orders', {'id': 'o', 'owner': 'u', 'organization_id': org, 'workflow_version': 3,
                          'state': 'cancelled', 'paused': True, 'version': 4, 'delivery_version': 2,
                          'generation_limit': 2, 'rerun_limit': 1, 'slots': [{'versions': [{'id': 'i', 'asset_id': raw['id']}]}],
                          'final_entries': [{'asset_id': raw['id']}], 'artifacts': []})
        tx.put('items', {'id': 'i', 'owner': 'u', 'organization_id': org, 'order_id': 'o', 'workflow_version': 3,
                         'credit_exempt': True, 'billing_legacy': True, 'status': 'unknown', 'generation_id': 'g',
                         'remote_reserved': True, 'fal_request_id': 'synthetic-request', 'raw_result_id': raw['id'],
                         'cutout_inflight': True})
        tx.put('generations', {'id': 'g', 'owner': 'u', 'organization_id': org, 'order_id': 'o', 'item_id': 'i',
                               'status': 'review', 'request_id': 'synthetic-request', 'created_at': '2020-01-01T00:00:00Z'})
        tx.put('credit_ledger', {'id': 'ledger', 'owner': 'u', 'event': 'reserve'})
        tx.put('credit_operations', {'id': 'operation', 'owner': 'u'})
        for key in ('drop-workflow-version-v1', 'drop-credits-v1'):
            tx.delete('migrations', key)
    return db, raw


def test_single_order_migration_drops_exact_fields_and_preserves_all_other_records(tmp_path):
    db, raw = legacy_fixture(tmp_path)
    before = snapshot(db)
    original = (db.root / 'assets' / raw['file']).read_bytes()
    migrated = Database(tmp_path)
    after = snapshot(migrated)
    first_after = deepcopy(after)
    expected = deepcopy(before)
    expected[('orders', 'o')].pop('workflow_version')
    for field in ('workflow_version', 'credit_exempt', 'billing_legacy'):
        expected[('items', 'i')].pop(field)
    expected[('users', 'u')].pop('credits')
    expected.pop(('credit_ledger', 'ledger'))
    expected.pop(('credit_operations', 'operation'))
    assert after.get(('migrations', 'drop-workflow-version-v1')) == {'id': 'drop-workflow-version-v1'}
    assert after.get(('migrations', 'drop-credits-v1')) == {'id': 'drop-credits-v1'}
    for key in (('migrations', 'drop-workflow-version-v1'), ('migrations', 'drop-credits-v1')):
        after.pop(key)
    assert after == expected
    assert (db.root / 'assets' / raw['file']).read_bytes() == original
    assert snapshot(Database(tmp_path)) == first_after


@pytest.mark.parametrize('kind,version', [('orders', 1), ('orders', None), ('items', 2), ('items', None), ('items', '3'), ('items', 3.0)])
def test_mixed_or_missing_workflow_version_refuses_before_business_mutation(tmp_path, kind, version):
    db, raw = legacy_fixture(tmp_path)
    with db.transaction() as tx:
        value = tx.get(kind, 'o' if kind == 'orders' else 'i')
        if version is None:
            value.pop('workflow_version')
        else:
            value['workflow_version'] = version
        tx.put(kind, value)
        # Even an old migration must not write before the strict preflight.
        tx.delete('migrations', 'order-shared-rerun-v1')
        config = tx.get('config', 'settings')
        config['rpm'] = 7
        tx.put('config', config)
    before = snapshot(db)
    with pytest.raises(ValueError, match='旧订单|单一订单|workflow'):
        Database(tmp_path)
    assert snapshot(db) == before


def test_new_database_never_recreates_credit_fields_or_workflow_index(tmp_path):
    db = Database(tmp_path)
    with db.transaction(readonly=True) as tx:
        assert tx.get('migrations', 'drop-workflow-version-v1')
        assert tx.get('migrations', 'drop-credits-v1')
        names = {row[0] for row in tx.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert 'records_workflow_version' not in names


def test_removed_legacy_and_credit_apis_and_new_account_shape(tmp_path, monkeypatch):
    from backend.app.main import create_app
    monkeypatch.setenv('STUDIO_OSS_BUCKET', '')
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        assert client.post('/api/auth/setup', json={'username': 'synthetic-admin', 'password': 'safe-password-123', 'display_name': '合成管理员'}).status_code == 200
        for path in ('/api/orders', '/api/orders/absent', '/api/credits', '/api/admin/users/absent/credits'):
            assert client.get(path).status_code == 404
        for path in ('/api/orders', '/api/orders/absent/pause', '/api/orders/absent/repack',
                     '/api/admin/users/absent/credits', '/api/admin/generations/absent/settle'):
            assert client.post(path, json={}).status_code == 404
        # Removing APIs must not change method errors for current endpoints.
        assert client.put('/api/customer-orders', json={}).status_code == 405
    with app.state.db.transaction(readonly=True) as tx:
        assert all('credits' not in user for user in tx.all('users'))


def test_new_customer_orders_and_items_never_write_retired_fields(tmp_path, monkeypatch):
    from backend.app.main import create_app
    from backend.app.customer_orders import new_item
    monkeypatch.setenv('STUDIO_OSS_BUCKET', '')
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as client:
        assert client.post('/api/auth/setup', json={'username': 'synthetic-admin', 'password': 'safe-password-123', 'display_name': '合成管理员'}).status_code == 200
        result = client.post('/api/customer-orders', json={'order_number': 'SYNTHETIC-MIGRATION', 'generation_limit': 1,
                                                          'final_count': 1, 'rerun_limit': 0, 'client_token': 'create'})
        assert result.status_code == 200
        with app.state.db.transaction() as tx:
            order = tx.get('orders', result.json()['id'])
            assert 'workflow_version' not in order
            item = new_item(tx, order, 'synthetic-item', 'synthetic-avatar',
                            {'id': 'synthetic-sticker', 'revision': 1, 'image': {'id': 'synthetic-template'}}, 1000, 0)
            assert all(field not in item for field in ('workflow_version', 'credit_exempt', 'billing_legacy'))
            assert tx.get('generations', item['generation_id'])['status'] == 'exempt'


def test_request_tracking_preserves_generation_status_and_other_fields(tmp_path):
    from backend.app import request_tracking
    db, _ = legacy_fixture(tmp_path)
    before = snapshot(db)[('generations', 'g')]
    with db.transaction() as tx:
        item = tx.get('items', 'i')
        item.update(status='failed', fal_request_id='synthetic-new-request', remote_reserved=False)
        request_tracking.progress(tx, item)
    assert snapshot(db)[('generations', 'g')] == before | {'request_id': 'synthetic-new-request'}
