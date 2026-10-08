"""卖家备注只来自销售平台：开户推送带入，提交拼图前和后台手动获取时经阿奇索订单查询更新（目前接入拼多多 Trade/Detail）。站内不可编辑。"""
import asyncio
import logging
from . import agiso_protocol as protocol
from .platforms import PLATFORMS, platform_of

log = logging.getLogger(__name__)


def remark_source(tx, order, now):
    """(shop, tid) for an Agiso-linked order, otherwise a status: no_link or unavailable (authorization expired)."""
    link = tx.get('agiso_orders', order.get('agiso_id') or '') if order.get('agiso_id') else None
    shop = tx.get('agiso_shops', link.get('shop_id', '')) if link else None
    if not link or not link.get('tid') or not shop or shop.get('organization_id') != order.get('organization_id'):
        return 'no_link'
    if not PLATFORMS[platform_of(shop)]['remark_sync']:
        return 'no_link'
    if not shop.get('token') or shop.get('expires_at', 0) <= now:
        return 'unavailable'
    return shop, str(link['tid'])


async def fetch_remark(source, config, transport, now):
    """Current seller remark text, or None when it could not be read."""
    if isinstance(source, str) or not config['configured']:
        return None
    try:
        result = await protocol.api('Trade/Detail', {'tid': source[1]}, source[0], config, transport, now)
    except Exception as error:
        log.warning('Seller remark lookup failed: %s', type(error).__name__)
        return None
    data = result.get('Data')
    if result.get('IsSuccess') is not True or not isinstance(data, dict) or not isinstance(data.get('remark'), (str, type(None))):
        log.warning('Seller remark lookup rejected: error_code=%s', result.get('Error_Code'))
        return None
    return (data.get('remark') or '').strip()[:2000]


def apply_remark(order, remark, republish):
    """Stores a changed remark; submitted orders re-layout their print pages when asked. Caller saves the order."""
    if order.get('platform_remark', '') == remark:
        return False
    order['platform_remark'] = remark
    if republish and order['state'] == 'submitted':
        order.update(delivery_ready=False, delivery_version=order['delivery_version'] + 1, publish_signatures={}, processing_error=None)
    return True


async def sync_submitted(db, order_id, transport, clock):
    """Once per submission, before the print pages are laid out. A failed lookup keeps the previous remark."""
    from .customer_orders import audit
    with db.transaction() as tx:
        order = tx.get('orders', order_id)
        if not order or order['state'] != 'submitted' or not order.get('remark_sync_pending'):
            return
        source = remark_source(tx, order, clock())
    remark = await fetch_remark(source, protocol.settings(), transport, clock())
    with db.transaction() as tx:
        latest = tx.get('orders', order_id)
        if not latest or not latest.get('remark_sync_pending'):
            return
        changed = remark is not None and apply_remark(latest, remark, republish=False)
        latest.update(remark_sync_pending=False, remark_sync={'status': 'ok' if remark is not None else 'failed', 'at': clock()})
        latest['version'] += 1
        tx.put('orders', latest)
        if changed:
            audit(tx, latest, 'remark_sync', 'agiso', clock())


async def sync_orders(db, ids, actor, transport, clock):
    """Staff fetch for chosen orders: changed remarks are stored and submitted orders re-laid out."""
    from .customer_orders import audit
    config = protocol.settings()
    with db.transaction() as tx:
        sources = {id: remark_source(tx, tx.get('orders', id), clock()) for id in ids}
    limit = asyncio.Semaphore(4)

    async def lookup(id, source):
        if isinstance(source, str):
            return id, source, None
        async with limit:
            remark = await fetch_remark(source, config, transport, clock())
        return id, 'failed' if remark is None else 'ok', remark

    fetched = await asyncio.gather(*(lookup(id, source) for id, source in sources.items()))
    results = []
    with db.transaction() as tx:
        for id, status, remark in fetched:
            order = tx.get('orders', id)
            if status != 'no_link':
                if status == 'ok':
                    status = 'updated' if apply_remark(order, remark, republish=True) else 'unchanged'
                order['remark_sync'] = {'status': 'failed' if status in {'failed', 'unavailable'} else 'ok', 'at': clock()}
                order['version'] += 1
                tx.put('orders', order)
                if status == 'updated':
                    audit(tx, order, 'remark_sync', actor, clock())
            results.append({'id': id, 'order_number': order['order_number'], 'status': status, 'remark': order.get('platform_remark', '')})
    return results
