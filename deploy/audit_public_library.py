#!/usr/bin/env python3
"""Read-only production integrity evidence; emits hashes, never account secrets."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def audit(data_dir):
    root = Path(data_dir)
    connection = sqlite3.connect((root / 'studio.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    connection.execute('BEGIN')
    integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
    rows = connection.execute('SELECT kind,id,doc FROM records ORDER BY kind,id').fetchall()
    connection.close()
    records = {}
    for kind, id, raw in rows:
        records.setdefault(kind, {})[id] = json.loads(raw)
    hashes = {kind:{id:digest(doc) for id,doc in docs.items()} for kind,docs in records.items()}
    account_state_hashes = {id:digest({k:v for k,v in doc.items() if k != 'can_edit_library'})
                            for id,doc in records.get('users', {}).items()}
    files, failures = {}, []
    for id, asset in records.get('assets', {}).items():
        path = root / 'assets' / asset['file']
        try:
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            files[id] = sha
            if sha != asset['sha256']:
                failures.append('asset hash mismatch: ' + id)
        except OSError:
            failures.append('asset unreadable: ' + id)
    refs = set()
    for kind in ('templates', 'template_revisions'):
        for doc in records.get(kind, {}).values():
            refs.update(image['id'] for image in doc.get('images', []))
    for kind in ('stickers', 'sticker_revisions'):
        refs.update(doc['image']['id'] for doc in records.get(kind, {}).values())
    for order in records.get('orders', {}).values():
        refs.add(order['avatar_id'])
        refs.update(a['id'] for a in order.get('artifacts', []))
    for item in records.get('items', {}).values():
        refs.update(item[k] for k in ('template_id', 'result_id', 'raw_result_id') if item.get(k))
    failures.extend('missing referenced asset: ' + id for id in sorted(refs - set(files)))
    templates = [{k:t.get(k) for k in ('id','code','name','active','deleted','revision','sticker_ids')} for t in records.get('templates', {}).values()]
    active_codes = [t['code'].casefold() for t in templates if not t.get('deleted')]
    if len(active_codes) != len(set(active_codes)):
        failures.append('duplicate unarchived template code')
    public_owners = {id:a.get('owner') for id,a in records.get('assets', {}).items() if a['kind']=='template' and a.get('owner') is not None}
    return {'integrity':integrity, 'counts':{k:len(v) for k,v in records.items()}, 'record_hashes':hashes,
            'asset_hashes':files, 'account_state_hashes':account_state_hashes, 'templates':templates, 'nonpublic_template_asset_count':len(public_owners),
            'inflight':sum(i.get('status') in ('running','unknown') or bool(i.get('remote_reserved')) for i in records.get('items', {}).values()),
            'failures':failures}


def compare(before, after):
    failures = []
    before_accounts = before.get('account_state_hashes')
    after_accounts = after.get('account_state_hashes')
    if before_accounts is None or after_accounts is None:
        failures.append('missing account state evidence; capture a fresh baseline')
    elif before_accounts != after_accounts:
        failures.append('account membership or state changed beyond library permission')
    # These histories must remain byte-for-byte equivalent after catalog migration.
    # Do this comparison with work drained and service stopped or idle.
    for kind in ('orders','items','generations','credit_ledger','credit_operations','uploads','template_revisions'):
        for id, value in before['record_hashes'].get(kind, {}).items():
            if after['record_hashes'].get(kind, {}).get(id) != value:
                failures.append(f'changed or missing historical {kind}: {id}')
    for id, value in before['asset_hashes'].items():
        if after['asset_hashes'].get(id) != value:
            failures.append('changed or missing original asset: ' + id)
    if after['nonpublic_template_asset_count']:
        failures.append('template assets retain private owner')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default='/var/lib/avatar-sticker-studio')
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    result = audit(args.data_dir)
    if args.baseline:
        result['failures'].extend(compare(json.loads(args.baseline.read_text()), result))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if result['integrity'] != 'ok' or result['failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
