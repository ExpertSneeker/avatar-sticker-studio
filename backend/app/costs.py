"""Per-order cost statistics.

Fixed costs (packaging, shipping, printing sheets) follow the order itself; per-call charges are
`cost_entries` records with an idempotent id, a day (Asia/Shanghai unless an offset is given), a
quantity and/or a recorded amount. Amounts priced from editable rates use the rate in effect on the
entry's day, so editing a rate only changes days from its effective date on.
"""
import io
import json
import logging
import math
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import HTTPException
from PIL import Image
from .storage import asset_bytes

log = logging.getLogger(__name__)

CHINA = timezone(timedelta(hours=8))
# Rates in CNY. Agiso bills per push or API call by tier (base/high/increment); prices are its current list prices.
RATE_FIELDS = ('packaging', 'shipping', 'sheet', 'per_sheet', 'cutout', 'agiso_base', 'agiso_high', 'agiso_increment')
DEFAULT_RATES = {'from': '1970-01-01', 'packaging': 0.3, 'shipping': 2.3, 'sheet': 0.27, 'per_sheet': 6, 'cutout': 0.032,
                 'agiso_base': 0.001, 'agiso_high': 0.002, 'agiso_increment': 0.004}
# Used only before the first daily USD/CNY rate is stored.
FALLBACK_USD_CNY = 7.1
CATEGORIES = ('packaging', 'shipping', 'material', 'generation', 'cutout', 'agiso', 'oss', 'esa')


def day_of(seconds, zone=CHINA):
    return datetime.fromtimestamp(seconds, zone).date().isoformat()


def rate_versions(config):
    return sorted(config.get('cost_rates') or [DEFAULT_RATES], key=lambda r: r['from'])


def rates_on(versions, day):
    """The version in effect on `day`; days before the first version use the first one."""
    current = versions[0]
    for version in versions:
        if version['from'] <= day:
            current = version
    return current


def fx_on(tx, day):
    """USD/CNY on `day`: the latest stored rate on or before it, else the earliest stored, else the fallback."""
    row = tx.conn.execute("SELECT doc FROM records WHERE kind='fx_rates' AND id<=? ORDER BY id DESC LIMIT 1", (day,)).fetchone() \
        or tx.conn.execute("SELECT doc FROM records WHERE kind='fx_rates' ORDER BY id LIMIT 1").fetchone()
    if not row:
        return {'usd_cny': FALLBACK_USD_CNY, 'source': 'fallback', 'id': None}
    return json.loads(row[0])


def printed_count(order):
    return len(order.get('final_entries') or [])


def sheets_for(count, per_sheet):
    """Each sheet cuts `per_sheet` stickers; an order of one sticker still uses a whole sheet."""
    return max(1, math.ceil(count / per_sheet)) if count else 0


def fixed_costs(order, versions, today):
    """Packaging, shipping and sheets: actual once shipped, estimated while submitted, none otherwise."""
    count = printed_count(order)
    if order.get('shipped_at'):
        basis, day = 'actual', day_of(order['shipped_at'])
    elif order['state'] == 'submitted' and count:
        basis, day = 'estimate', today
    else:
        return {'packaging': 0.0, 'shipping': 0.0, 'material': 0.0}, None, 0
    rate = rates_on(versions, day)
    sheets = sheets_for(count, rate['per_sheet'])
    return {'packaging': rate['packaging'], 'shipping': rate['shipping'], 'material': sheets * rate['sheet']}, basis, sheets


def entry_amount(entry, versions, fx):
    """CNY for one cost entry."""
    if entry.get('amount_cny') is not None:
        return entry['amount_cny']
    if entry.get('amount_usd') is not None:
        return entry['amount_usd'] * fx(entry['day'])['usd_cny']
    rate = rates_on(versions, entry['day'])
    return entry.get('quantity', 0) * rate[entry['rate']]


def cutout_checked_ids(tx):
    return {row[0][len('cutout:'):] for row in tx.conn.execute("SELECT id FROM records WHERE kind='cost_entries' AND id LIKE 'cutout:%'")}


def sync_cutouts(db, *, limit=200):
    """One entry per finished item: 1 when Yezi returned a cutout (billed only on success), else 0.
    Items from before `cutout_used` existed are inferred from their original: a customer image in
    cutout mode was cut out exactly when it had no transparency."""
    with db.transaction(readonly=True) as tx:
        done = cutout_checked_ids(tx)
        pending = [i for i in tx.where('items', 'status', 'completed') if i['id'] not in done][:limit]
        orders = {}
        work = []
        for item in pending:
            order = orders.get(item['order_id']) or orders.setdefault(item['order_id'], tx.get('orders', item['order_id']) or {})
            raw = tx.get('assets', item['raw_result_id']) if (not item.get('cutout_used') and item.get('source') == 'design'
                    and item.get('cutout_mode') == 'cutout' and item.get('raw_result_id')) else None
            work.append((item, order, raw))
    entries = []
    for item, order, raw in work:
        used = 1 if item.get('cutout_used') else 0
        if raw is not None:
            try:
                with Image.open(io.BytesIO(asset_bytes(db, raw))) as image:
                    used = int(image.convert('RGBA').getchannel('A').getextrema()[0] == 255)
            except Exception:
                used = 0  # original no longer available (deleted after shipping): nothing provable
        when = item.get('started_at') or (datetime.fromisoformat(order['created_at']).timestamp() if order.get('created_at') else 0)
        entries.append({'id': 'cutout:' + item['id'], 'source': 'cutout', 'order_id': item['order_id'],
                        'organization_id': item.get('organization_id'), 'item_id': item['id'], 'day': day_of(when),
                        'quantity': used, 'rate': 'cutout', 'basis': 'actual' if item.get('cutout_used') or raw is None else 'inferred'})
    if entries:
        with db.transaction() as tx:
            for entry in entries:
                tx.put('cost_entries', entry)
    return len(entries)


def fetch_usd_cny(get=None):
    """Today's USD/CNY: CFETS central parity first (official, reachable in mainland China), open.er-api second."""
    get = get or (lambda url: httpx.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'}, follow_redirects=True))
    try:
        data = get('https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json').json()
        price = next(float(r['price']) for r in data['records'] if r.get('vrtEName') == 'USD/CNY')
        if 5 < price < 10:
            return {'usd_cny': price, 'source': 'cfets', 'published': (data.get('data') or {}).get('lastDate')}
    except Exception:
        log.warning('CFETS USD/CNY unavailable; trying the fallback source')
    data = get('https://open.er-api.com/v6/latest/USD').json()
    price = float(data['rates']['CNY'])
    if not 5 < price < 10:
        raise ValueError('implausible USD/CNY rate')
    return {'usd_cny': price, 'source': 'open.er-api.com', 'published': data.get('time_last_update_utc')}


def sync_fx(db, now, get=None):
    """Store one USD/CNY rate per China day; retries hourly until it succeeds."""
    today = day_of(now)
    with db.transaction(readonly=True) as tx:
        state = tx.get('cost_sync', 'fx') or {}
        if tx.get('fx_rates', today) or 'attempted_at' in state and state['attempted_at'] > now - 3600:
            return False
    with db.transaction() as tx:
        tx.put('cost_sync', {'id': 'fx', 'attempted_at': now})
    rate = fetch_usd_cny(get)
    with db.transaction() as tx:
        tx.put('fx_rates', {'id': today, **rate, 'fetched_at': now})
    return True


def tick(db, now, get=None):
    """Periodic cost syncs; each source fails on its own without stopping the others.
    `get` replaces outbound HTTP in tests and local browser runs."""
    for name, job in (('fx', lambda: sync_fx(db, now, get)), ('cutout', lambda: sync_cutouts(db))):
        try:
            job()
        except Exception:
            log.warning('Cost sync %s failed; will retry', name)


def report(tx, actor, now, date_from, date_to, *, offset=480, global_scope=False, platform=None, shop_id=None):
    """Orders created between the two China days, with each cost category per order."""
    from .customer_orders import scoped
    from .platforms import platform_of
    zone = timezone(timedelta(minutes=offset))
    today = day_of(now, zone)
    config = tx.get('config', 'settings')
    versions = rate_versions(config)
    fx_cache = {}
    def fx(day):
        if day not in fx_cache:
            fx_cache[day] = fx_on(tx, day)
        return fx_cache[day]
    orders = []
    for order in tx.all('orders'):
        if not (global_scope or scoped(order, actor)):
            continue
        created = datetime.fromisoformat(order['created_at']).astimezone(zone).date().isoformat()
        if date_from and created < date_from or date_to and created > date_to:
            continue
        if platform and platform_of(order) != platform or shop_id and order.get('shop_id') != shop_id:
            continue
        orders.append((order, created))
    ids = {o['id'] for o, _ in orders}
    by_order = {}
    for entry in tx.all('cost_entries'):
        if entry.get('order_id') in ids:
            by_order.setdefault(entry['order_id'], []).append(entry)
    shops = {s['id']: s.get('shop_name', '') for s in tx.all('agiso_shops')}
    rows, totals = [], {c: 0.0 for c in CATEGORIES}
    printed_total = sheets_total = 0
    for order, created in orders:
        costs = {c: 0.0 for c in CATEGORIES}
        fixed, basis, sheets = fixed_costs(order, versions, today)
        costs.update(fixed)
        counts = {}
        for entry in by_order.get(order['id'], []):
            costs[entry['source']] += entry_amount(entry, versions, fx)
            counts[entry['source']] = counts.get(entry['source'], 0) + entry.get('quantity', 0)
        costs = {c: round(v, 4) for c, v in costs.items()}
        for c in CATEGORIES:
            totals[c] += costs[c]
        printed = printed_count(order) if basis else 0
        printed_total += printed
        sheets_total += sheets
        rows.append({'id': order['id'], 'order_number': order['order_number'], 'state': order['state'], 'created': created,
                     'platform': platform_of(order), 'shop_name': shops.get(order.get('shop_id'), ''),
                     'shipped_at': order.get('shipped_at'), 'printed': printed, 'sheets': sheets, 'fixed_basis': basis,
                     'cutouts': counts.get('cutout', 0), 'costs': costs, 'total': round(sum(costs.values()), 4)})
    rows.sort(key=lambda r: (r['created'], r['order_number']), reverse=True)
    total = round(sum(totals.values()), 4)
    current = fx(today)
    return {'date_from': date_from, 'date_to': date_to, 'today': today, 'scope': 'global' if global_scope else 'organization',
            'rates': rates_on(versions, today), 'rate_versions': versions,
            'fx': {'usd_cny': current['usd_cny'], 'source': current['source'], 'day': current.get('id'), 'published': current.get('published')},
            'summary': {'orders': len(rows), 'printed': printed_total, 'sheets': sheets_total, 'total': total,
                        'per_order': round(total / len(rows), 4) if rows else 0, 'per_sticker': round(total / printed_total, 4) if printed_total else 0,
                        'categories': {c: round(v, 4) for c, v in totals.items()}},
            'orders': rows}


def save_rates(tx, data):
    """Add (or replace) the rate version effective from `data['from']`."""
    config = tx.get('config', 'settings')
    versions = [v for v in rate_versions(config) if v['from'] != data['from']]
    versions.append({'from': data['from'], **{k: data[k] for k in RATE_FIELDS}})
    config['cost_rates'] = sorted(versions, key=lambda r: r['from'])
    tx.put('config', config)
    return config['cost_rates']


def register_costs(app, db, user, admin, superadmin):
    from fastapi import Query, Request
    from .schemas import CostRates
    now = app.state.clock

    @app.get('/api/costs')
    def costs(request: Request, date_from: str | None = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
              date_to: str | None = Query(None, pattern=r'^\d{4}-\d{2}-\d{2}$'), scope: str = 'organization',
              platform: str | None = None, shop_id: str | None = None, offset: int = Query(480, ge=-720, le=840)):
        with db.transaction(readonly=True) as tx:
            actor = superadmin(tx, request) if scope == 'global' else admin(tx, request)
            if scope != 'global' and not actor.get('organization_id'):
                raise HTTPException(409, '请先关联组织')
            return report(tx, actor, now(), date_from, date_to, offset=offset, global_scope=scope == 'global',
                          platform=platform, shop_id=shop_id)

    @app.put('/api/costs/rates')
    def put_rates(data: CostRates, request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
            return {'rate_versions': save_rates(tx, data.model_dump(by_alias=True))}
