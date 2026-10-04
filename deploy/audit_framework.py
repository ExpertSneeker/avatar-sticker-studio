#!/usr/bin/env python3
"""Read-only framework migration audit; JSON contains hashes, never credentials.

--rehearse migrates a temporary SQLite backup, without starting a worker or
copying/modifying source assets. Invoke using the new release's Python runtime.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from copy import deepcopy

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def valid_oss_marker(order, artifact):
    sha = artifact.get('sha256')
    return (artifact.get('kind') == 'print' and isinstance(sha, str)
            and re.fullmatch('[0-9a-f]{64}', sha) and order.get('organization_id') and order.get('id')
            and artifact['oss_key'] == f"print/{order['organization_id']}/{order['id']}/{sha}.png")


def historical_content(kind, doc, allow_oss_delivery=False, allow_single_order_migration=False):
    if allow_oss_delivery or allow_single_order_migration:
        # Stage A changes no business/tenant/generation field. Its only permitted
        # bookkeeping difference is the exact current content-addressed print key.
        value = deepcopy(doc)
        if kind == 'orders':
            for artifact in value.get('artifacts', []):
                if 'oss_key' in artifact and valid_oss_marker(doc, artifact):
                    artifact.pop('oss_key')
        if allow_single_order_migration:
            fields = {'orders': ('workflow_version',), 'items': ('workflow_version', 'credit_exempt', 'billing_legacy'),
                      'users': ('credits',)}
            for field in fields.get(kind, ()):
                value.pop(field, None)
        return value
    # Tenant metadata is the intended migration. Business snapshots remain exact.
    value = {k: v for k, v in doc.items() if k != 'organization_id'}
    if kind == 'users':
        value = {k: v for k, v in value.items() if k not in {'role', 'credits', 'organization_name'}}
    if kind == 'generations':
        value = {k: v for k, v in value.items() if k not in {'status', 'settled_at'}}
    return value


def referenced_assets(records):
    refs = set()
    for kind in ('templates', 'template_revisions'):
        for doc in records.get(kind, {}).values():
            refs.update(im['id'] for im in doc.get('images', []) if im.get('id'))
    for kind in ('stickers', 'sticker_revisions'):
        for doc in records.get(kind, {}).values():
            if doc.get('image', {}).get('id'):
                refs.add(doc['image']['id'])
    for doc in records.get('orders', {}).values():
        if doc.get('avatar_id'):
            refs.add(doc['avatar_id'])
        for avatar in doc.get('avatars', []):
            asset_id = avatar.get('asset_id') or avatar.get('avatar_id')
            if asset_id:
                refs.add(asset_id)
        refs.update(a['id'] for a in doc.get('artifacts', []) if a.get('id'))
        for slot in doc.get('slots', []):
            refs.update(v['asset_id'] for v in slot.get('versions', []) if v.get('asset_id'))
            sticker_asset = slot.get('sticker', {}).get('image', {}).get('id')
            if sticker_asset:
                refs.add(sticker_asset)
        refs.update(e['asset_id'] for e in doc.get('final_entries', []) if e.get('asset_id'))
        if doc.get('overview_id'):
            refs.add(doc['overview_id'])
    for kind in ('items', 'result_versions'):
        for doc in records.get(kind, {}).values():
            refs.update(doc[k] for k in ('avatar_id', 'template_id', 'result_id', 'raw_result_id', 'asset_id') if doc.get(k))
    return refs


def audit(data_dir, assets_dir=None, *, allow_oss_delivery=False, allow_single_order_migration=False):
    if allow_oss_delivery and allow_single_order_migration:
        raise ValueError('choose one explicit comparison mode')
    root = Path(data_dir)
    assets = Path(assets_dir) if assets_dir else root / 'assets'
    conn = sqlite3.connect((root / 'studio.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('BEGIN')
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        rows = conn.execute('SELECT kind,id,doc FROM records ORDER BY kind,id').fetchall()
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()
    records = {}
    for kind, identifier, raw in rows:
        records.setdefault(kind, {})[identifier] = json.loads(raw)
    failures, files = [], {}
    migration = None
    if allow_single_order_migration:
        migration = {
            'workflow_marker': 'drop-workflow-version-v1' in records.get('migrations', {}),
            'credits_marker': 'drop-credits-v1' in records.get('migrations', {}),
            'workflow_fields': sum('workflow_version' in doc for kind in ('orders', 'items') for doc in records.get(kind, {}).values()),
            'workflow_index': 'records_workflow_version' in indexes,
            'credit_fields': sum('credits' in doc for doc in records.get('users', {}).values()) + sum(
                ('credit_exempt' in doc) + ('billing_legacy' in doc) for doc in records.get('items', {}).values()),
            'credit_records': sum(len(records.get(kind, {})) for kind in ('credit_ledger', 'credit_operations')),
        }
        if not migration['workflow_marker']:
            if any(type(doc.get('workflow_version')) is not int or doc['workflow_version'] != 3
                   for kind in ('orders', 'items') for doc in records.get(kind, {}).values()):
                failures.append('single-order migration requires all orders and items at workflow version 3')
        elif migration['workflow_fields'] or migration['workflow_index']:
            failures.append('single-order migration left workflow fields or index')
        if migration['credits_marker'] and (migration['credit_fields'] or migration['credit_records']):
            failures.append('single-order migration left credit fields or records')
    if allow_oss_delivery or allow_single_order_migration:
        for order in records.get('orders', {}).values():
            if any('oss_key' in artifact and not valid_oss_marker(order, artifact)
                   for artifact in order.get('artifacts', [])):
                failures.append('invalid OSS delivery marker: ' + order['id'])
    for identifier, asset in records.get('assets', {}).items():
        filename = asset.get('file', '')
        if not filename or Path(filename).name != filename or assets.is_symlink() or (assets / filename).is_symlink():
            failures.append('unsafe asset path: ' + identifier)
            continue
        try:
            sha = hashlib.sha256((assets / filename).read_bytes()).hexdigest()
            files[identifier] = sha
            if sha != asset.get('sha256'):
                failures.append('asset hash mismatch: ' + identifier)
        except OSError:
            failures.append('asset unreadable: ' + identifier)
    failures.extend('missing referenced asset: ' + identifier for identifier in sorted(referenced_assets(records) - files.keys()))
    for kind in ('stickers', 'templates'):
        seen = set()
        for doc in records.get(kind, {}).values():
            if doc.get('deleted'):
                continue
            key = (doc.get('organization_id'), doc.get('code', '').casefold())
            if key in seen:
                failures.append('duplicate organization catalog code: ' + doc['id'])
            seen.add(key)
    seen = set()
    for doc in records.get('orders', {}).values():
        if not doc.get('order_number'):
            continue
        if doc['order_number'] in seen:
            failures.append('duplicate customer order number: ' + doc['id'])
        seen.add(doc['order_number'])
    organizations = records.get('organizations', {})
    if organizations:
        for kind in ('users', 'orders', 'assets', 'stickers', 'templates', 'uploads', 'items'):
            for doc in records.get(kind, {}).values():
                if doc.get('role') == 'superadmin' and not doc.get('organization_id'):
                    continue
                if doc.get('organization_id') not in organizations:
                    failures.append('missing organization: ' + kind + ':' + doc['id'])
    items = list(records.get('items', {}).values())
    return {
        'format_version': 1, 'comparison_mode': 'single-order-migration' if allow_single_order_migration else 'oss-delivery' if allow_oss_delivery else 'framework', 'integrity': integrity,
        'counts': {kind: len(docs) for kind, docs in records.items()},
        'record_hashes': {kind: {key: digest(doc) for key, doc in docs.items()} for kind, docs in records.items()},
        'historical_hashes': {kind: {key: digest(historical_content(kind, doc, allow_oss_delivery, allow_single_order_migration)) for key, doc in docs.items()} for kind, docs in records.items()},
        'asset_hashes': files,
        'inflight': sum(i.get('status') in {'running', 'unknown'} or bool(i.get('remote_reserved')) or bool(i.get('cutout_inflight')) for i in items),
        'queued': sum(i.get('status') == 'queued' for i in items),
        'failures': failures,
        **({'single_order_migration': migration} if migration is not None else {}),
    }


def compare(before, after):
    failures = []
    if before.get('comparison_mode', 'framework') != after.get('comparison_mode', 'framework'):
        return ['comparison mode mismatch']
    if before.get('format_version') != 1 or after.get('format_version') != 1:
        return ['audit format mismatch']
    if not isinstance(before.get('historical_hashes'), dict) or not isinstance(before.get('asset_hashes'), dict):
        return ['invalid audit baseline']
    if before.get('failures') or before.get('integrity') != 'ok':
        failures.append('baseline contains audit failures')
    single = before.get('comparison_mode') == 'single-order-migration'
    if single:
        migration = after.get('single_order_migration', {})
        if not migration.get('workflow_marker') or not migration.get('credits_marker'):
            failures.append('single-order migration markers incomplete')
        failures.extend(after.get('failures', []))
        if migration.get('workflow_fields') or migration.get('workflow_index') or migration.get('credit_fields') or migration.get('credit_records'):
            failures.append('single-order migration deletion incomplete')
    protected = ('users', 'orders', 'items', 'generations', 'uploads', 'assets',
                 'templates', 'stickers', 'library_categories', 'template_revisions',
                 'sticker_revisions', 'credit_ledger', 'credit_operations', 'config')
    if single:
        # A release restarts worker leases; all other preexisting collections,
        # including future kinds, idempotence and Agiso history, remain protected.
        # New migration markers are additions, not rewrites of existing markers.
        protected = sorted(before['historical_hashes'].keys() - {'credit_ledger', 'credit_operations', 'workers'})
    for kind in protected:
        for identifier, sha in before['historical_hashes'].get(kind, {}).items():
            if after['historical_hashes'].get(kind, {}).get(identifier) != sha:
                failures.append('changed or missing historical ' + kind + ': ' + identifier)
    for identifier, sha in before['asset_hashes'].items():
        if after['asset_hashes'].get(identifier) != sha:
            failures.append('changed or missing original asset: ' + identifier)
    return failures


def rehearse(data_dir, *, allow_oss_delivery=False, allow_single_order_migration=False):
    root = Path(data_dir).resolve()
    options = {'allow_oss_delivery': allow_oss_delivery, 'allow_single_order_migration': allow_single_order_migration}
    before = audit(root, **options)
    with tempfile.TemporaryDirectory(prefix='sticker-framework-rehearsal-') as tmp:
        source = sqlite3.connect((root / 'studio.sqlite3').as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(Path(tmp) / 'studio.sqlite3')
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        from backend.app.db import Database
        migrated = Database(tmp)
        migrated.close()
        after = audit(tmp, root / 'assets', **options)
        migrated = Database(tmp)
        migrated.close()
        repeated = audit(tmp, root / 'assets', **options)
        failures = before['failures'] + after['failures'] + compare(before, after)
        if after['record_hashes'] != repeated['record_hashes']:
            failures.append('migration is not idempotent')
        return {'comparison_mode': before['comparison_mode'], 'source': before, 'migrated': after,
                'idempotent': after['record_hashes'] == repeated['record_hashes'], 'failures': failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--rehearse', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--allow-oss-delivery', action='store_true',
                        help='Compare all fields strictly except exact print artifact OSS markers; use for both baseline and current audit')
    mode.add_argument('--allow-single-order-migration', action='store_true',
                      help='Permit only workflow/credit field and ledger deletion; preserve generations and assets exactly')
    args = parser.parse_args()
    try:
        options = {'allow_oss_delivery': args.allow_oss_delivery, 'allow_single_order_migration': args.allow_single_order_migration}
        report = rehearse(args.data_dir, **options) if args.rehearse else audit(args.data_dir, **options)
        if args.baseline:
            if args.rehearse:
                parser.error('--baseline and --rehearse are separate operations')
            report['failures'].extend(compare(json.loads(args.baseline.read_text()), report))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        raise SystemExit(1 if report['failures'] or report.get('integrity', 'ok') != 'ok' else 0)
    except (sqlite3.Error, OSError, ValueError):
        # Never print raw database content or credentials in exception messages.
        print(json.dumps({'failures': ['audit could not read or validate the selected data directory']}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
