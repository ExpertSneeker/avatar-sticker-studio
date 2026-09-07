"""Publish a frozen occurrence list without duplicating paid generation work."""
import hashlib
import json
from .processing import PRINT_LAYOUT_STYLE, overview, pack_set
from .schemas import PrintSettings
from .storage import save_asset


def publish_selection(db, order, items, binaries, owner, force=False, watermark_only=False):
    entries = order['export_entries']
    lookup = {i['id']: i for i in items}
    if not entries or any(e['item_id'] not in lookup for e in entries):
        raise ValueError('导出清单包含无效生成项')
    if any(i['status'] != 'completed' or i['id'] not in binaries for i in items):
        return False
    ordered = [binaries[e['item_id']] for e in entries]
    refs = [(e, lookup[e['item_id']]['result_id']) for e in entries]
    watermark = owner['watermark'] or owner['display_name']
    signatures = dict(order.get('publish_signatures', {}))
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    print_signature = digest([PRINT_LAYOUT_STYLE, order['name'], order['print_settings'], refs])
    overview_signature = digest([refs, watermark, 'bold-outline-shadow-v3'])
    needs_print = not watermark_only and (force or signatures.get('_merged') != print_signature)
    needs_overview = force or signatures.get('_overview') != overview_signature
    if not needs_print and not needs_overview:
        return False
    pages = pack_set(ordered, order['name'], '拼版', PrintSettings(**order['print_settings'])) if needs_print else []
    preview = overview(ordered, watermark) if needs_overview else None
    with db.transaction() as tx:
        latest = tx.get('orders', order['id'])
        if not latest or latest['content_version'] != order['content_version']:
            return False
        if needs_print:
            artifacts = []
            for entry in entries:
                asset = tx.get('assets', lookup[entry['item_id']]['result_id'])
                artifacts.append({k:asset[k] for k in ('id','url','sha256','size')} | {
                    'kind':'sticker', 'path':f"{order['name']}_{entry['code']}_{entry['copy_index']}.png",
                    'sticker_id':entry['sticker_id'], 'item_id':entry['item_id']})
            for filename, data in pages:
                asset = save_asset(db, tx, data, order['owner'], 'print', order_id=order['id'])
                artifacts.append({k:asset[k] for k in ('id','url','sha256','size','kind')} | {'path':filename})
            signatures['_merged'] = print_signature
        else:
            artifacts = [a for a in latest['artifacts'] if a['kind'] != 'overview']
        if preview is not None:
            asset = save_asset(db, tx, preview, order['owner'], 'overview', order_id=order['id'])
            artifacts.append({k:asset[k] for k in ('id','url','sha256','size','kind')} | {'path':order['name']+'_水印总览.png'})
            signatures['_overview'] = overview_signature
        else:
            artifacts.extend(a for a in latest['artifacts'] if a['kind']=='overview')
        latest.update(artifacts=artifacts, artifact_version=latest['artifact_version']+1,
                      overview_ready=True, overview_style='bold-outline-shadow-v3',
                      publish_signatures=signatures, processing_error=None)
        tx.put('orders', latest)
    return True
