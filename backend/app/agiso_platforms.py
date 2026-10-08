"""Douyin and Xiaohongshu adapters: push classification, validation and Agiso API calls.

Pinduoduo keeps its original code path (agiso_protocol models, agiso_routes webhook, agiso_service).
These adapters turn each platform's pushes and API responses into the shared shapes below, so the
opening, quota, conflict and refund logic in agiso_service stays one implementation. Field names and
codes come from docs/agiso-reference (aldsDoudian, aldsXhs); verify against real pushes before trusting
new fields.

Normalized trade:  {tid, order_number, paid_cents, buyer_memo, remark, status, items: [{goods_id, sku_id,
                    goods_count, goods_name, goods_spec}]}
Normalized refund: {tid, refund_id, refund_fee (cents), modified, bill_type (1 money refund, 99 other),
                    operation (1304 success, 1300 released, 0 pending)} -- the Pinduoduo-shaped dict
                    agiso_service.apply_refund already understands.
"""
import asyncio
from decimal import Decimal, InvalidOperation
from . import agiso_protocol as protocol
from .agiso_protocol import identifier

SUCCESS, RELEASED, PENDING = 1304, 1300, 0


def _id(value):
    """Platform ids may arrive as JSON numbers beyond 2**53; Python keeps them exact, store as text."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('invalid id')
    return identifier(str(value))


def _text(value, limit=2000):
    return value.strip()[:limit] if isinstance(value, str) else ''


def _int(value, default=0):
    if isinstance(value, bool):
        raise ValueError('invalid number')
    if value is None or value == '':
        return default
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        raise ValueError('invalid number')


def _yuan_cents(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('invalid amount')
    if not amount.is_finite() or amount < 0:
        raise ValueError('invalid amount')
    return int((amount * 100).to_integral_value())


def _ok(result):
    if result.get('IsSuccess') is not True or not isinstance(result.get('Data'), dict):
        raise protocol.ProtocolError()
    return result['Data']


class Douyin:
    platform = 'douyin'
    # aopic: 1 付款成功; 2 买家发起售后; 4 售后关闭; 8 退款成功; others are informational.
    families = {'1': 'trade', '2': 'refund', '4': 'refund', '8': 'refund'}
    refund_operation = {'2': PENDING, '4': RELEASED, '8': SUCCESS}
    # 售后类型 0 退货 1 售后仅退款 2 发货前退款 are money refunds; 换货/价保/补寄 need a person.
    money_refunds = {0, 1, 2}

    def push_identity(self, family, payload):
        """(platform shop key, order id) from a validated push."""
        return _id(payload['shop_id']), _id(payload['p_id'])

    def refund(self, topic, payload):
        stamp = payload.get('success_time') or payload.get('close_time') or payload.get('apply_time')
        return {'tid': _id(payload['p_id']), 'refund_id': _id(payload['aftersale_id']),
                'refund_fee': _int(payload.get('refund_amount')), 'modified': max(_int(stamp, 1), 1),
                'bill_type': 1 if _int(payload.get('aftersale_type'), -1) in self.money_refunds else 99,
                'operation': self.refund_operation[topic]}

    async def trade(self, shop, tid, config, transport, now):
        data = _ok(await protocol.api('Order/Detail', {'shop_order_id': tid}, shop, config, transport, now))
        items = []
        for row in data.get('sku_order_list') or []:
            spec = ' '.join(_text(s.get('value'), 200) for s in row.get('spec') or [] if isinstance(s, dict))
            items.append({'goods_id': _id(row['product_id']), 'sku_id': _id(row['sku_id']),
                          'goods_count': _int(row.get('item_num'), 1), 'goods_name': _text(row.get('product_name'), 1000),
                          'goods_spec': spec[:1000]})
        status = _int(data.get('order_status'), 0)
        return {'tid': _id(data.get('order_id') or tid), 'order_number': _id(data.get('order_id') or tid),
                'paid_cents': _int(data.get('pay_amount')), 'buyer_memo': _text(data.get('buyer_words')),
                'remark': _text(data.get('seller_words')), 'items': items,
                # 1 待支付, 4 已取消: never open; everything else has been paid.
                'status': 'unpaid' if status == 1 else 'cancelled' if status == 4 else 'paid',
                'shop_key': _id(data['shop_id']) if data.get('shop_id') not in (None, '') else None}

    async def remark(self, shop, tid, config, transport, now):
        data = _ok(await protocol.api('Order/Detail', {'shop_order_id': tid}, shop, config, transport, now))
        return _text(data.get('seller_words'))

    async def goods(self, shop, page, name, config, transport, now):
        """Product/List has no SKUs; each product's Product/Detail lists them (sell_properties = spec)."""
        listing = _ok(await protocol.api('Product/List', {'page': str(page), 'size': '20'}, shop, config, transport, now))
        products = listing.get('data') if isinstance(listing.get('data'), list) else []
        if name:
            products = [p for p in products if name in _text(p.get('name'), 1000)]
        gate = asyncio.Semaphore(5)

        async def detail(product):
            async with gate:
                pid = _id(product.get('product_id_str') or product['product_id'])
                data = _ok(await protocol.api('Product/Detail', {'productId': pid}, shop, config, transport, now))
                skus = []
                for sku in data.get('spec_prices') or []:
                    label = ' '.join(_text(p.get('value_name'), 200) for p in sku.get('sell_properties') or [] if isinstance(p, dict))
                    skus.append({'sku_id': _id(sku['sku_id']), 'sku_name': label or _text(sku.get('code'), 200)})
                return {'goods_id': pid, 'goods_name': _text(data.get('name') or product.get('name'), 1000), 'skus': skus}

        rows = await asyncio.gather(*(detail(p) for p in products))
        return {'goods': list(rows), 'total': _int(listing.get('total'), len(rows))}


class Xiaohongshu:
    platform = 'xhs'
    # aopic: 4 付款成功; 16 买家申请退款; 32 退款成功; 1/2/8 are informational. No after-sale close push.
    families = {'4': 'trade', '16': 'refund', '32': 'refund'}
    refund_operation = {'16': PENDING, '32': SUCCESS}
    # 退货类型 1 退货退款 3/4/5 仅退款 are money refunds; 2 换货 needs a person.
    money_refunds = {1, 3, 4, 5}
    # Order/Detail returns sku ids only, so rules match on SKU id alone.
    match_on_sku_only = True

    def push_identity(self, family, payload):
        return _id(payload['sellerId']), _id(payload['orderId'])

    def refund(self, topic, payload):
        return {'tid': _id(payload['orderId']), 'refund_id': _id(payload['returnsId']),
                'refund_fee': _yuan_cents(payload.get('refundFee', 0)), 'modified': max(_int(payload.get('updateTime'), 1), 1),
                'bill_type': 1 if _int(payload.get('returnType'), -1) in self.money_refunds else 99,
                'operation': self.refund_operation[topic]}

    async def trade(self, shop, tid, config, transport, now):
        data = _ok(await protocol.api('Order/Detail', {'tid': tid}, shop, config, transport, now))
        items, paid = [], 0
        for row in data.get('skuList') or []:
            if row.get('skuTag') == 1:
                continue  # gifts never carry a sticker quota
            items.append({'goods_id': '', 'sku_id': _id(row['skuId']), 'goods_count': _int(row.get('skuQuantity'), 1),
                          'goods_name': _text(row.get('skuName'), 1000), 'goods_spec': _text(row.get('skuSpec'), 1000)})
            paid += _int(row.get('totalPaidAmount'))
        status = _int(data.get('orderStatus'), 0)
        return {'tid': _id(data.get('orderId') or tid), 'order_number': _id(data.get('orderId') or tid),
                'paid_cents': paid, 'buyer_memo': '', 'remark': '', 'items': items,
                # 1 待付款, 8 已关闭, 9 已取消: never open.
                'status': 'unpaid' if status == 1 else 'cancelled' if status in (8, 9) else 'paid', 'shop_key': None}

    async def remark(self, shop, tid, config, transport, now):
        return None  # Order/Detail has no seller remark field

    async def goods(self, shop, page, name, config, transport, now):
        listing = _ok(await protocol.api('Product/GetList', {'page_no': str(page), 'page_size': '100'}, shop, config, transport, now))
        by_item = {}
        for row in listing.get('data') or []:
            item, sku = row.get('item') or {}, row.get('sku') or {}
            title = _text(item.get('name') or sku.get('name'), 1000)
            if name and name not in title:
                continue
            gid = _id(item.get('id') or sku.get('itemId'))
            spec = ' '.join(_text(v.get('value'), 200) for v in sku.get('variants') or [] if isinstance(v, dict))
            entry = by_item.setdefault(gid, {'goods_id': gid, 'goods_name': title, 'skus': []})
            entry['skus'].append({'sku_id': _id(sku['id']), 'sku_name': spec or _text(sku.get('name'), 200)})
        return {'goods': list(by_item.values()), 'total': _int(listing.get('total'), len(by_item))}


ADAPTERS = {'douyin': Douyin(), 'xhs': Xiaohongshu()}
