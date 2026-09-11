#!/usr/bin/env python3
"""Read-only framework migration audit; JSON contains hashes, never credentials.

--rehearse migrates a temporary SQLite backup, without starting a worker or
copying/modifying source assets. Invoke using the new release's Python runtime.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def historical_content(kind, doc):
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


def audit(data_dir, assets_dir=None):
    root = Path(data_dir)
    assets = Path(assets_dir) if assets_dir else root / 'assets'
    conn = sqlite3.connect((root / 'studio.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('BEGIN')
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        rows = conn.execute('SELECT kind,id,doc FROM records ORDER BY kind,id').fetchall()
    finally:
        conn.close()
    records = {}
    for kind, identifier, raw in rows:
        records.setdefault(kind, {})[identifier] = json.loads(raw)
    failures, files = [], {}
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
        'format_version': 1, 'integrity': integrity,
        'counts': {kind: len(docs) for kind, docs in records.items()},
        'record_hashes': {kind: {key: digest(doc) for key, doc in docs.items()} for kind, docs in records.items()},
        'historical_hashes': {kind: {key: digest(historical_content(kind, doc)) for key, doc in docs.items()} for kind, docs in records.items()},
        'asset_hashes': files,
        'inflight': sum(i.get('status') in {'running', 'unknown'} or bool(i.get('remote_reserved')) or bool(i.get('cutout_inflight')) for i in items),
        'queued': sum(i.get('status') == 'queued' for i in items),
        'failures': failures,
    }


def compare(before, after):
    failures = []
    # Credit generations may settle/release, but ledger rows are append-only.
    for kind in ('users', 'orders', 'items', 'generations', 'uploads', 'template_revisions', 'sticker_revisions', 'credit_ledger', 'credit_operations', 'config'):
        for identifier, sha in before['historical_hashes'].get(kind, {}).items():
            if after['historical_hashes'].get(kind, {}).get(identifier) != sha:
                failures.append('changed or missing historical ' + kind + ': ' + identifier)
    for identifier, sha in before['asset_hashes'].items():
        if after['asset_hashes'].get(identifier) != sha:
            failures.append('changed or missing original asset: ' + identifier)
    return failures


def rehearse(data_dir):
    root = Path(data_dir).resolve()
    before = audit(root)
    with tempfile.TemporaryDirectory(prefix='sticker-framework-rehearsal-') as tmp:
        source = sqlite3.connect((root / 'studio.sqlite3').as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(Path(tmp) / 'studio.sqlite3')
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        from backend.app.db import Database
        Database(tmp)
        after = audit(tmp, root / 'assets')
        Database(tmp)
        repeated = audit(tmp, root / 'assets')
        failures = before['failures'] + after['failures'] + compare(before, after)
        if after['record_hashes'] != repeated['record_hashes']:
            failures.append('migration is not idempotent')
        return {'source': before, 'migrated': after, 'idempotent': after['record_hashes'] == repeated['record_hashes'], 'failures': failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--rehearse', action='store_true')
    args = parser.parse_args()
    try:
        report = rehearse(args.data_dir) if args.rehearse else audit(args.data_dir)
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
