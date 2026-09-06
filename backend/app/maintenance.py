"""Administrator cleanup: preview, transactional ownership removal, durable file deletion."""
import hashlib
import json
import re
import shutil
from datetime import datetime
from .previews import CACHE_LIMIT, cache_lock, cached_files, remove_asset_cache

OUTPUT_KINDS = {'raw_result', 'result', 'print', 'overview'}


def _references(orders, items):
    result = {o['avatar_id'] for o in orders}
    result.update(a['id'] for o in orders for a in o.get('artifacts', []))
    result.update(i[k] for i in items for k in ('result_id', 'raw_result_id', 'template_id') if i.get(k))
    return result


def cleanup_plan(db, tx, before):
    orders, items, assets = tx.all('orders'), tx.all('items'), tx.all('assets')
    older = [o for o in orders if datetime.fromisoformat(o['created_at']).timestamp() < before.timestamp()]
    blocked = {i['order_id'] for i in items if i['status'] in {'running', 'unknown'} or i.get('remote_reserved')}
    blocked.update(g['order_id'] for g in tx.all('generations') if g['status']=='review')
    chosen = [o for o in older if o['id'] not in blocked]
    ids = {o['id'] for o in chosen}
    selected_items = [i for i in items if i['order_id'] in ids]
    remaining_orders = [o for o in orders if o['id'] not in ids]
    remaining_items = [i for i in items if i['order_id'] not in ids]
    referenced = _references(chosen, selected_items)
    protected = _references(remaining_orders, remaining_items)
    protected.update(im['id'] for kind in ('templates', 'template_revisions') for t in tx.all(kind) for im in t['images'])
    surviving_owners = {o['owner'] for o in remaining_orders}
    deleted_owners = {o['owner'] for o in chosen}
    all_refs = _references(orders, items)
    removable, unassigned = [], []
    for asset in assets:
        if asset['kind'] == 'template' or asset['id'] in protected:
            continue
        if asset.get('order_id') in ids or asset['id'] in referenced:
            removable.append(asset)
        elif not asset.get('order_id') and asset['kind'] in OUTPUT_KINDS and asset['id'] not in all_refs:
            # Older releases did not tag historical outputs. Only reclaim when no order of that owner remains.
            if asset['owner'] in deleted_owners and asset['owner'] not in surviving_owners:
                removable.append(asset)
            else:
                unassigned.append(asset)
    asset_ids = {a['id'] for a in removable}
    uploads = [u for u in tx.all('uploads') if u.get('asset_id') in asset_ids]
    paths = ['assets/' + a['file'] for a in removable] + [u['id']+'.upload' for u in uploads]
    sizes = []
    for path in paths:
        try: sizes.append((db.root/path).lstat().st_size)
        except FileNotFoundError: sizes.append(0)
    previews = cached_files(db, asset_ids)
    preview_bytes = 0
    for path in previews:
        try: preview_bytes += path.stat().st_size
        except FileNotFoundError: pass
    # Directory tombstones remove every variant, including ones created after preview.
    paths += ['preview-cache/' + id for id in asset_ids]
    fingerprint = json.dumps([before.isoformat(), chosen, selected_items, removable, uploads], sort_keys=True)
    public = {'before': before.isoformat(), 'preview_token': hashlib.sha256(fingerprint.encode()).hexdigest(), 'order_count': len(chosen), 'item_count': len(selected_items), 'file_count': len(sizes) + len(previews), 'file_bytes': sum(sizes) + preview_bytes, 'preview_cache_files': len(previews), 'preview_cache_bytes': preview_bytes, 'blocked_count': sum(o['id'] in blocked for o in older), 'legacy_unassigned_files': len(unassigned), 'orders': [{'id':o['id'],'name':o['name'],'created_at':o['created_at']} for o in chosen[:50]]}
    reruns = [r for r in tx.all('rerun_operations') if r['order_id'] in ids]
    return public, {'orders':chosen, 'items':selected_items, 'assets':removable, 'uploads':uploads, 'rerun_operations':reruns}, paths


def stage_cleanup(tx, records, paths):
    for kind, values in records.items():
        for value in values:
            tx.delete(kind, value['id'])
    for path in paths:
        tx.put('cleanup_files', {'id':hashlib.sha256(path.encode()).hexdigest(), 'path':path})


def drain_cleanup(db):
    with db.transaction() as tx:
        pending = tx.all('cleanup_files')
    for value in pending:
        path = value['path']
        # Paths come from trusted records; still never follow arbitrary paths or directory symlinks.
        if re.fullmatch(r'preview-cache/[0-9a-f]{32}', path):
            try:
                with cache_lock(db):
                    remove_asset_cache(db, path.split('/')[1])
            except OSError:
                continue
            with db.transaction() as tx:
                tx.delete('cleanup_files', value['id'])
            continue
        if not re.fullmatch(r'(?:assets/[0-9a-f]{32}\.png|[0-9a-f]{32}\.upload)', path):
            continue
        if path.startswith('assets/') and (db.root/'assets').is_symlink():
            continue
        try:
            (db.root/path).unlink(missing_ok=True)
        except OSError:
            continue
        with db.transaction() as tx:
            tx.delete('cleanup_files', value['id'])
    with db.transaction() as tx:
        return len(tx.all('cleanup_files'))


def storage_stats(db):
    disk = shutil.disk_usage(db.root)
    app_bytes = 0
    for path in db.root.rglob('*'):
        if path.is_file() and not path.is_symlink():
            try: app_bytes += path.stat().st_size
            except FileNotFoundError: pass
    with db.transaction() as tx:
        pending = len(tx.all('cleanup_files'))
    preview_bytes = 0
    for path in cached_files(db):
        try: preview_bytes += path.stat().st_size
        except FileNotFoundError: pass
    return {'preview_cache_bytes':preview_bytes, 'preview_cache_limit_bytes':CACHE_LIMIT, 'total_bytes':disk.total, 'used_bytes':disk.used, 'free_bytes':disk.free, 'app_bytes':app_bytes, 'pending_files':pending}
