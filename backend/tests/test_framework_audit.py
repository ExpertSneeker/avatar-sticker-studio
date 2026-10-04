"""Release audit must detect data loss without disclosing production credentials."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

from deploy import audit_framework


def seed(root):
    root.mkdir(exist_ok=True)
    (root / 'assets').mkdir()
    payload = b'original-asset-bytes'
    (root / 'assets' / 'asset.png').write_bytes(payload)
    docs = {
        'assets': [{'id': 'asset', 'file': 'asset.png', 'sha256': hashlib.sha256(payload).hexdigest(), 'kind': 'avatar', 'owner': 'u'}],
        'users': [{'id': 'u', 'username': 'magnus', 'password': 'must-never-leak', 'role': 'admin', 'active': True}],
        'orders': [{'id': 'o', 'owner': 'u', 'avatar_id': 'asset', 'name': 'historical', 'artifacts': [], 'template_snapshots': [{'id': 'old-template', 'revision': 3}]}],
        'items': [],
        'config': [{'id': 'settings', 'fal_api_key': 'secret-api-key', 'prompt': 'private-prompt', 'max_inflight': 2}],
    }
    with sqlite3.connect(root / 'studio.sqlite3') as conn:
        conn.execute('CREATE TABLE records(kind TEXT, id TEXT, doc TEXT, PRIMARY KEY(kind,id))')
        for kind, values in docs.items():
            for doc in values:
                conn.execute('INSERT INTO records VALUES(?,?,?)', (kind, doc['id'], json.dumps(doc)))
    return docs


def replace(root, kind, doc):
    with sqlite3.connect(root / 'studio.sqlite3') as conn:
        conn.execute('UPDATE records SET doc=? WHERE kind=? AND id=?', (json.dumps(doc), kind, doc['id']))


def test_audit_is_read_only_redacted_and_detects_changed_original(tmp_path):
    seed(tmp_path)
    before = (tmp_path / 'studio.sqlite3').read_bytes()
    report = audit_framework.audit(tmp_path)
    assert report['integrity'] == 'ok'
    assert report['failures'] == []
    assert report['counts']['orders'] == 1
    assert (tmp_path / 'studio.sqlite3').read_bytes() == before
    rendered = json.dumps(report)
    assert all(secret not in rendered for secret in ['must-never-leak', 'secret-api-key', 'private-prompt'])
    (tmp_path / 'assets' / 'asset.png').write_bytes(b'tampered')
    assert 'asset hash mismatch: asset' in audit_framework.audit(tmp_path)['failures']


def test_compare_allows_tenant_metadata_but_rejects_snapshot_rewrite(tmp_path):
    docs = seed(tmp_path)
    before = audit_framework.audit(tmp_path)
    order = docs['orders'][0] | {'organization_id': 'org'}
    replace(tmp_path, 'orders', order)
    replace(tmp_path, 'users', docs['users'][0] | {'role': 'org_admin', 'organization_id': 'org'})
    assert audit_framework.compare(before, audit_framework.audit(tmp_path)) == []
    order['template_snapshots'][0]['revision'] = 4
    replace(tmp_path, 'orders', order)
    assert 'changed or missing historical orders: o' in audit_framework.compare(before, audit_framework.audit(tmp_path))


def test_new_order_multiple_avatar_references_are_checked(tmp_path):
    docs = seed(tmp_path)
    order = docs['orders'][0] | {'workflow_version': 3, 'avatars': [{'id': 'a', 'asset_id': 'missing-avatar'}]}
    order.pop('avatar_id')
    replace(tmp_path, 'orders', order)
    assert 'missing referenced asset: missing-avatar' in audit_framework.audit(tmp_path)['failures']


def test_customer_version_and_frozen_final_references_cannot_be_orphaned(tmp_path):
    docs = seed(tmp_path)
    order = docs['orders'][0] | {'workflow_version':3, 'slots':[{'versions':[{'id':'v','asset_id':'missing-version'}]}], 'final_entries':[{'asset_id':'missing-final'}]}
    replace(tmp_path, 'orders', order)
    failures = audit_framework.audit(tmp_path)['failures']
    assert 'missing referenced asset: missing-version' in failures
    assert 'missing referenced asset: missing-final' in failures


def test_audit_cli_failure_is_nonzero_and_never_writes_source(tmp_path):
    seed(tmp_path)
    (tmp_path / 'assets' / 'asset.png').unlink()
    script = Path(audit_framework.__file__)
    result = subprocess.run([sys.executable, str(script), '--data-dir', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)['failures']
    assert 'secret-api-key' not in result.stdout + result.stderr


def test_compare_rejects_missing_generation_history_and_configuration_changes(tmp_path):
    docs = seed(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute('INSERT INTO records VALUES(?,?,?)', ('generations', 'g', json.dumps({'id':'g','item_id':'i','status':'review','request_id':'remote-request'})))
    before = audit_framework.audit(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute("DELETE FROM records WHERE kind='generations'")
    assert 'changed or missing historical generations: g' in audit_framework.compare(before, audit_framework.audit(tmp_path))
    replace(tmp_path, 'config', docs['config'][0] | {'max_inflight': 40})
    assert 'changed or missing historical config: settings' in audit_framework.compare(before, audit_framework.audit(tmp_path))


@pytest.mark.parametrize('kind', ['stickers', 'templates', 'library_categories', 'assets'])
def test_compare_preserves_live_catalog_and_asset_metadata(tmp_path, kind):
    seed(tmp_path)
    if kind != 'assets':
        with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
            conn.execute('INSERT INTO records VALUES(?,?,?)', (kind, 'catalog', json.dumps({'id':'catalog','code':'A1','name':'Original'})))
    before = audit_framework.audit(tmp_path)
    identifier = 'asset' if kind == 'assets' else 'catalog'
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        raw = conn.execute('SELECT doc FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()[0]
    document = json.loads(raw)
    replace(tmp_path, kind, document | {'organization_id':'new-organization'})
    assert audit_framework.compare(before, audit_framework.audit(tmp_path)) == []
    replace(tmp_path, kind, document | {'name':'Unexpected rewrite'})
    assert f'changed or missing historical {kind}: {identifier}' in audit_framework.compare(before, audit_framework.audit(tmp_path))
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, identifier))
    assert f'changed or missing historical {kind}: {identifier}' in audit_framework.compare(before, audit_framework.audit(tmp_path))


def print_order(root):
    docs = seed(root)
    sha = docs['assets'][0]['sha256']
    order = docs['orders'][0] | {'organization_id': 'org', 'state': 'submitted', 'delivery_ready': True,
                                'delivery_version': 3, 'artifacts': [{'id': 'asset', 'kind': 'print', 'sha256': sha, 'size': 20}]}
    replace(root, 'orders', order)
    return order, f'print/org/o/{sha}.png'


def test_oss_comparison_allows_only_expected_print_key_addition_and_removal(tmp_path):
    order, key = print_order(tmp_path)
    before = audit_framework.audit(tmp_path, allow_oss_delivery=True)
    strict_before = audit_framework.audit(tmp_path)
    order['artifacts'][0]['oss_key'] = key
    replace(tmp_path, 'orders', order)
    after = audit_framework.audit(tmp_path, allow_oss_delivery=True)
    assert before['comparison_mode'] == after['comparison_mode'] == 'oss-delivery'
    assert audit_framework.compare(before, after) == []
    assert audit_framework.compare(after, before) == []
    assert 'changed or missing historical orders: o' in audit_framework.compare(strict_before, audit_framework.audit(tmp_path))
    assert audit_framework.compare(strict_before, after) == ['comparison mode mismatch']


@pytest.mark.parametrize('kind,key', [('print', 'print/foreign/o/invalid.png'), ('overview', 'expected'), ('print', None)])
def test_oss_comparison_rejects_malformed_and_nonprint_markers(tmp_path, kind, key):
    order, expected = print_order(tmp_path)
    order['artifacts'][0].update(kind=kind, oss_key=expected if key == 'expected' else key)
    replace(tmp_path, 'orders', order)
    report = audit_framework.audit(tmp_path, allow_oss_delivery=True)
    assert 'invalid OSS delivery marker: o' in report['failures']
    assert 'foreign' not in json.dumps(report)


@pytest.mark.parametrize('change', ['hash', 'asset', 'state', 'version', 'generation'])
def test_oss_comparison_keeps_all_other_business_fields_strict(tmp_path, change):
    order, key = print_order(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute('INSERT INTO records VALUES(?,?,?)', ('generations', 'g', json.dumps({'id': 'g', 'status': 'reserved'})))
    before = audit_framework.audit(tmp_path, allow_oss_delivery=True)
    order['artifacts'][0]['oss_key'] = key
    if change == 'hash': order['artifacts'][0]['sha256'] = '0' * 64
    elif change == 'asset': order['artifacts'][0]['id'] = 'different'
    elif change == 'state': order['state'] = 'cancelled'
    elif change == 'version': order['delivery_version'] += 1
    elif change == 'generation': replace(tmp_path, 'generations', {'id': 'g', 'status': 'settled'})
    replace(tmp_path, 'orders', order)
    changed_kind = 'generations: g' if change == 'generation' else 'orders: o'
    assert 'changed or missing historical ' + changed_kind in audit_framework.compare(before, audit_framework.audit(tmp_path, allow_oss_delivery=True))


def test_oss_audit_cli_requires_same_explicit_mode_in_baseline(tmp_path):
    order, key = print_order(tmp_path)
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps(audit_framework.audit(tmp_path)))
    script = Path(audit_framework.__file__)
    args = [sys.executable, str(script), '--data-dir', str(tmp_path), '--allow-oss-delivery', '--baseline', str(baseline)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 1 and 'comparison mode mismatch' in json.loads(result.stdout)['failures']
    baseline.write_text(json.dumps(audit_framework.audit(tmp_path, allow_oss_delivery=True)))
    order['artifacts'][0]['oss_key'] = key
    replace(tmp_path, 'orders', order)
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0 and not json.loads(result.stdout)['failures']


def test_oss_rehearsal_uses_explicit_mode_and_leaves_source_unmodified(tmp_path):
    from backend.app.db import Database
    db = Database(tmp_path)
    before = (tmp_path / 'studio.sqlite3').read_bytes()
    report = audit_framework.rehearse(tmp_path, allow_oss_delivery=True)
    assert report['comparison_mode'] == report['source']['comparison_mode'] == report['migrated']['comparison_mode'] == 'oss-delivery'
    assert report['idempotent'] and report['failures'] == []
    assert (tmp_path / 'studio.sqlite3').read_bytes() == before


def single_order_seed(root):
    docs = seed(root)
    replace(root, 'users', docs['users'][0] | {'credits': {'available': 4}})
    replace(root, 'orders', docs['orders'][0] | {'workflow_version': 3, 'state': 'review', 'delivery_version': 2})
    rows = {
        'items': {'id': 'i', 'order_id': 'o', 'workflow_version': 3, 'credit_exempt': True,
                  'billing_legacy': True, 'status': 'unknown', 'remote_reserved': True,
                  'fal_request_id': 'provider-request', 'raw_result_id': 'asset'},
        'generations': {'id': 'g', 'item_id': 'i', 'order_id': 'o', 'status': 'review',
                        'request_id': 'provider-request', 'settled_at': 'original-time'},
        'credit_ledger': {'id': 'ledger', 'amount': 1},
        'credit_operations': {'id': 'operation', 'fingerprint': 'original'},
    }
    with sqlite3.connect(root / 'studio.sqlite3') as conn:
        for kind, doc in rows.items():
            conn.execute('INSERT INTO records VALUES(?,?,?)', (kind, doc['id'], json.dumps(doc)))
        conn.execute("CREATE INDEX records_workflow_version ON records(kind, json_extract(doc,'$.workflow_version'))")


def simulate_single_order_migration(root):
    # Independently describe the authorized data transform to test the audit,
    # without depending on the migration implementation being audited.
    fields = {'orders': ('workflow_version',), 'items': ('workflow_version', 'credit_exempt', 'billing_legacy'),
              'users': ('credits',)}
    with sqlite3.connect(root / 'studio.sqlite3') as conn:
        for kind, keys in fields.items():
            for identifier, raw in conn.execute('SELECT id,doc FROM records WHERE kind=?', (kind,)).fetchall():
                doc = json.loads(raw)
                for key in keys:
                    doc.pop(key, None)
                conn.execute('UPDATE records SET doc=? WHERE kind=? AND id=?', (json.dumps(doc), kind, identifier))
        conn.execute("DELETE FROM records WHERE kind IN ('credit_ledger','credit_operations')")
        conn.execute('DROP INDEX records_workflow_version')
        for marker in ('drop-workflow-version-v1', 'drop-credits-v1'):
            conn.execute('INSERT INTO records VALUES(?,?,?)', ('migrations', marker, json.dumps({'id': marker})))


def test_single_order_audit_allows_only_authorized_deletions(tmp_path):
    single_order_seed(tmp_path)
    before = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    simulate_single_order_migration(tmp_path)
    after = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    assert before['failures'] == after['failures'] == []
    assert before['comparison_mode'] == after['comparison_mode'] == 'single-order-migration'
    assert audit_framework.compare(before, after) == []
    assert before['historical_hashes']['generations'] == after['historical_hashes']['generations']
    assert audit_framework.compare(audit_framework.audit(tmp_path), after) == ['comparison mode mismatch']


@pytest.mark.parametrize('kind,identifier,field,value', [
    ('generations', 'g', 'status', 'exempt'),
    ('generations', 'g', 'request_id', 'different'),
    ('items', 'i', 'remote_reserved', False),
    ('items', 'i', 'raw_result_id', None),
    ('orders', 'o', 'state', 'cancelled'),
    ('orders', 'o', 'delivery_version', 3),
    ('users', 'u', 'organization_id', 'foreign'),
])
def test_single_order_audit_rejects_request_and_business_rewrites(tmp_path, kind, identifier, field, value):
    single_order_seed(tmp_path)
    before = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    simulate_single_order_migration(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        doc = json.loads(conn.execute('SELECT doc FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()[0])
    replace(tmp_path, kind, doc | {field: value})
    assert f'changed or missing historical {kind}: {identifier}' in audit_framework.compare(
        before, audit_framework.audit(tmp_path, allow_single_order_migration=True))


@pytest.mark.parametrize('value', [None, 2, '3', 3.0])
def test_single_order_audit_rejects_unmigratable_baseline_versions(tmp_path, value):
    single_order_seed(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        doc = json.loads(conn.execute("SELECT doc FROM records WHERE kind='orders'").fetchone()[0])
    if value is None:
        doc.pop('workflow_version')
    else:
        doc['workflow_version'] = value
    replace(tmp_path, 'orders', doc)
    assert audit_framework.audit(tmp_path, allow_single_order_migration=True)['failures']


@pytest.mark.parametrize('leftover', ['marker', 'field', 'ledger', 'index'])
def test_single_order_audit_rejects_incomplete_migration(tmp_path, leftover):
    single_order_seed(tmp_path)
    before = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    simulate_single_order_migration(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        if leftover == 'marker':
            conn.execute("DELETE FROM records WHERE kind='migrations' AND id='drop-credits-v1'")
        elif leftover == 'ledger':
            conn.execute('INSERT INTO records VALUES(?,?,?)', ('credit_ledger', 'leftover', '{"id":"leftover"}'))
        elif leftover == 'index':
            conn.execute("CREATE INDEX records_workflow_version ON records(kind, json_extract(doc,'$.workflow_version'))")
        else:
            conn.execute("UPDATE records SET doc=json_set(doc,'$.credit_exempt',1) WHERE kind='items'")
    after = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    assert audit_framework.compare(before, after)


def test_single_order_cli_requires_matching_mode_and_complete_migration(tmp_path):
    single_order_seed(tmp_path)
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps(audit_framework.audit(tmp_path, allow_single_order_migration=True)))
    simulate_single_order_migration(tmp_path)
    args = [sys.executable, str(Path(audit_framework.__file__)), '--data-dir', str(tmp_path),
            '--allow-single-order-migration', '--baseline', str(baseline)]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['failures'] == []
    assert 'provider-request' not in result.stdout
    baseline.write_text(json.dumps(audit_framework.audit(tmp_path)))
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 1 and 'comparison mode mismatch' in json.loads(result.stdout)['failures']


def test_single_order_rehearsal_rejects_unsupported_source_without_writing(tmp_path):
    single_order_seed(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute("UPDATE records SET doc=json_set(doc,'$.workflow_version',2) WHERE kind='orders'")
    before = (tmp_path / 'studio.sqlite3').read_bytes()
    with pytest.raises(ValueError):
        audit_framework.rehearse(tmp_path, allow_single_order_migration=True)
    assert (tmp_path / 'studio.sqlite3').read_bytes() == before


@pytest.mark.parametrize('kind', ['customer_operations', 'customer_audit', 'result_versions',
                                  'agiso_orders', 'agiso_events', 'agiso_shops', 'invites',
                                  'watermark_previews', 'migrations', 'future_business_history'])
def test_single_order_compare_preserves_every_unrelated_historical_collection(tmp_path, kind):
    single_order_seed(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute('INSERT INTO records VALUES(?,?,?)', (kind, 'protected', '{"id":"protected","value":"original"}'))
    before = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    simulate_single_order_migration(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, 'protected'))
    after = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    assert f'changed or missing historical {kind}: protected' in audit_framework.compare(before, after)


def test_single_order_compare_allows_only_worker_lease_turnover(tmp_path):
    single_order_seed(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute('INSERT INTO records VALUES(?,?,?)', ('workers', 'previous', '{"id":"previous","expires":1}'))
    before = audit_framework.audit(tmp_path, allow_single_order_migration=True)
    simulate_single_order_migration(tmp_path)
    with sqlite3.connect(tmp_path / 'studio.sqlite3') as conn:
        conn.execute("DELETE FROM records WHERE kind='workers'")
        conn.execute('INSERT INTO records VALUES(?,?,?)', ('workers', 'current', '{"id":"current","expires":2}'))
    assert audit_framework.compare(before, audit_framework.audit(tmp_path, allow_single_order_migration=True)) == []
