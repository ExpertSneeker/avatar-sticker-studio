"""Release audit must detect data loss without disclosing production credentials."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

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
