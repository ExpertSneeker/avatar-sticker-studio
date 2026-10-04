"""Publish a frozen occurrence list without duplicating paid generation work."""
import hashlib
import json
from .processing import PRINT_LAYOUT_STYLE, overview, pack_set
from .schemas import PrintSettings
from .storage import save_asset


def customer_print_title(order):
    """客户订单打印页标题：订单号 + 卖家备注，过长时截断。"""
    remark = ' '.join((order.get('platform_remark') or '').split())[:60]
    return order['order_number'] + ((' ' + remark) if remark else '')


def publish_customer(db, order, force=False, watermark_only=False):
    """Freeze print-only output against exact submitted selection/settings/media snapshot."""
    if order['state'] != 'submitted' or not order.get('final_entries'):
        return False
    from .storage import asset_bytes
    entries = order['final_entries']
    with db.transaction() as tx:
        originals = [asset_bytes(db, tx.get('assets', e['asset_id'])) for e in entries]
    digest = lambda v: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()
    title = customer_print_title(order)
    print_signature = digest([PRINT_LAYOUT_STYLE, title, order['print_settings'], entries])
    overview_signature = digest([entries, order['watermark'], order['watermark_version'], 'guest-overview-v1'])
    previous = order.get('publish_signatures', {})
    needs_print = not watermark_only and (force or not order.get('delivery_ready') or previous.get('_merged') != print_signature)
    needs_overview = force or not order.get('overview_ready') or previous.get('_overview') != overview_signature
    if not needs_print and not needs_overview:
        return False
    pages = pack_set(originals, title, '拼版', PrintSettings(**order['print_settings'])) if needs_print else []
    # No notes enter any rendered image. The guest endpoint preserves this already watermarked overview.
    preview = overview(originals, order['watermark']) if needs_overview else None
    with db.transaction() as tx:
        latest = tx.get('orders', order['id'])
        if not latest or latest['state'] != 'submitted' or latest['content_version'] != order['content_version'] or latest['final_entries'] != entries:
            return False
        signatures = dict(latest.get('publish_signatures', {}))
        if needs_print:
            artifacts = []
            for page_number, (_, data) in enumerate(pages, 1):
                filename = f'page-{page_number:03}.png'
                asset = save_asset(db, tx, data, order['owner'], 'print', order_id=order['id'])
                artifacts.append({k:asset[k] for k in ('id','url','sha256','size','kind')} | {'path':filename})
            latest['artifacts'] = artifacts
            latest['delivery_ready'] = True
            signatures['_merged'] = print_signature
        if preview is not None:
            asset = save_asset(db, tx, preview, order['owner'], 'overview', order_id=order['id'])
            latest.update(overview_id=asset['id'], overview_ready=True, overview_style='guest-overview-v1')
            signatures['_overview'] = overview_signature
        latest.update(artifact_version=latest['artifact_version']+1, publish_signatures=signatures, processing_error=None)
        tx.put('orders', latest)
    return True
