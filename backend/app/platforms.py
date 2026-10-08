"""Sales platforms and their Agiso endpoints (see docs/agiso-reference/README.md).

Orders and shops carry a platform key. Platforms whose adapter exists (agiso_platforms.py) accept
authorization and pushes (`connectable`). `remark_sync`: the order detail API exposes the seller remark.
"""
from .media_cache import watermark_of

PLATFORMS = {
    'pdd': {'label': '拼多多', 'from_platform': 'PddAlds', 'token_platforms': ('PddAlds', 'AldsPdd'),
            'host': 'https://aldspdd.agiso.com', 'gateway': 'aldsPdd', 'connectable': True, 'remark_sync': True},
    'douyin': {'label': '抖店', 'from_platform': 'AldsDoudian', 'token_platforms': ('AldsDoudian',),
               'host': 'https://aldsDoudian.agiso.com', 'gateway': 'aldsDoudian', 'connectable': True, 'remark_sync': True,
               # Agiso sells two Douyin apps with separate authorization domains (aldsDoudian/guide.md). The
               # virtual one has no own docs; its token platform id is accepted and remembered on the shop.
               'apps': {'doudian': {'label': '自动发货', 'host': 'https://aldsDoudian.agiso.com'},
                        'dd': {'label': '虚拟自动发货', 'host': 'https://aldsdd.agiso.com', 'open_platform_id': True}}},
    'xhs': {'label': '小红书', 'from_platform': 'AldsXhs', 'token_platforms': ('AldsXhs',),
            'host': 'https://aldsXhs.agiso.com', 'gateway': 'aldsXhs', 'connectable': True, 'remark_sync': False},
}


def platform_of(value):
    """Platform key of an order, shop, link or event; everything before multi-platform was Pinduoduo."""
    return (value or {}).get('platform') or 'pdd'


def from_push(from_platform):
    return next((key for key, value in PLATFORMS.items() if value['from_platform'] == from_platform), None)


def app_of(platform, app):
    """Agiso app of a platform: (key, settings). Platforms with a single app use their own host."""
    apps = PLATFORMS[platform].get('apps')
    if not apps:
        return None, {'host': PLATFORMS[platform]['host']}
    key = app or next(iter(apps))
    if key not in apps:
        raise KeyError(key)
    return key, apps[key]


def gateway_of(shop):
    """API gateway prefix. A shop authorized through an app with its own platform id (e.g. AldsXxx) uses
    the matching aldsXxx prefix, the pattern of every documented Alds* app."""
    own = shop.get('from_platform') if shop else None
    if own and own != PLATFORMS[platform_of(shop)]['from_platform'] and own.startswith('Alds'):
        return own[0].lower() + own[1:]
    return PLATFORMS[platform_of(shop)]['gateway']


def shop_watermark(tx, shop):
    """Watermark for orders of a shop; a shop without one falls back to its owner's account watermark."""
    mark = (shop.get('watermark') or '').strip()
    if mark:
        return mark
    owner = tx.get('users', shop.get('owner', ''))
    return watermark_of(owner) if owner else ''


def migrate_platforms(tx):
    """platform-v1: every existing shop, link, event and order is Pinduoduo; shops take their
    owner's current watermark so newly opened orders keep exactly today's watermark."""
    if tx.get('migrations', 'platform-v1'):
        return
    for shop in tx.all('agiso_shops'):
        shop.setdefault('platform', 'pdd')
        if 'watermark' not in shop:
            owner = tx.get('users', shop['owner'])
            shop['watermark'] = watermark_of(owner) if owner else ''
        tx.put('agiso_shops', shop)
    for kind in ('agiso_orders', 'agiso_events'):
        for value in tx.all(kind):
            if 'platform' not in value:
                value['platform'] = 'pdd'
                tx.put(kind, value)
    for order in tx.all('orders'):
        changed = 'platform' not in order or 'shop_id' not in order
        order.setdefault('platform', 'pdd')
        if 'shop_id' not in order:
            link = tx.get('agiso_orders', order.get('agiso_id') or '') if order.get('agiso_id') else None
            order['shop_id'] = link['shop_id'] if link else None
        if changed:
            tx.put('orders', order)
    tx.put('migrations', {'id': 'platform-v1'})
