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
import os
import threading
import time
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
    get = get or (lambda url, **kw: httpx.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'}, follow_redirects=True))
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


FAL_API = 'https://api.fal.ai/v1/models'
FAL_START = '2026-09-01T00:00:00+00:00'
FAL_SETTLE = 3 * 3600
# Set when the service stops so a slow provider sync ends between requests instead of delaying shutdown.
STOP = threading.Event()


def http(get, url, **kwargs):
    """GET JSON with a few retries for rate limits and server errors."""
    get = get or (lambda url, **kw: httpx.get(url, timeout=30, **kw))
    for attempt in range(3):
        if STOP.is_set():
            raise RuntimeError('stopping')
        response = get(url, **kwargs)
        status = getattr(response, 'status_code', 200)
        if status == 200:
            return response.json()
        if status not in (429, 500, 502, 503, 504):
            break
        time.sleep(1 + 2 * attempt)
    raise RuntimeError(f'HTTP {status}')


def fal_pages(get, url, params, key):
    cursor = None
    while True:
        page = http(get, url, params={**params, **({'cursor': cursor} if cursor else {})}, headers={'Authorization': 'Key ' + key})
        yield page
        if not page.get('has_more'):
            return
        cursor = page.get('next_cursor')
        if not cursor:
            raise RuntimeError('missing cursor')


def fal_request_items(tx):
    """request id -> item, from every place a request id was kept."""
    found = {}
    for item in tx.all('items'):
        for rid in [item.get('fal_request_id'), *item.get('fal_request_ids', []), *(r.get('request_id') for r in item.get('fal_input_retries', []))]:
            if rid:
                found[rid] = item
    items = {i['id']: i for i in found.values()}
    for generation in tx.all('generations'):
        if generation.get('request_id') and generation['request_id'] not in found and generation.get('item_id') in items:
            found[generation['request_id']] = items[generation['item_id']]
    return found


def fal_window(get, key, start, end):
    """Actual FAL charges between two UTC instants, split per request.

    FAL reports cost per endpoint and minute; a request is charged in the minute it ended. Each
    minute's cost is shared equally by the successful requests that ended in it (all requests if
    none succeeded); minutes without any listed request stay as unattributed amounts. Returns
    None when the minute and hour totals disagree (data not final yet)."""
    window = {'start': start.isoformat(), 'end': end.isoformat()}
    minutes, total = {}, 0.0
    for page in fal_pages(get, FAL_API + '/usage', {**window, 'timeframe': 'minute', 'expand': 'time_series'}, key):
        for bucket in page.get('time_series', []):
            for result in bucket['results']:
                if result.get('cost'):
                    slot = (result['endpoint_id'], bucket['bucket'][:16])
                    minutes[slot] = minutes.get(slot, 0.0) + result['cost']
    for page in fal_pages(get, FAL_API + '/usage', {**window, 'timeframe': 'hour', 'expand': 'time_series'}, key):
        total += sum(r.get('cost') or 0 for b in page.get('time_series', []) for r in b['results'])
    if abs(total - sum(minutes.values())) > 1e-6:
        return None
    requests = {}
    listed = {**window, 'start': (start - timedelta(hours=2)).isoformat()}
    for endpoint in sorted({e for e, _ in minutes}):
        for page in fal_pages(get, FAL_API + '/requests/by-endpoint', {**listed, 'endpoint_id': endpoint, 'limit': 100}, key):
            for request in page.get('items', []):
                if request.get('ended_at'):
                    requests.setdefault((endpoint, request['ended_at'][:16]), []).append(request)
    shares = []
    for (endpoint, minute), cost in minutes.items():
        ended = requests.get((endpoint, minute), [])
        paid = [r for r in ended if r.get('status_code') == 200] or ended
        if paid:
            shares += [(r['request_id'], endpoint, minute, cost / len(paid)) for r in paid]
        else:
            shares.append((None, endpoint, minute, cost))
    return shares


def sync_fal(db, now, get=None, *, max_windows=3):
    """Hourly windows of settled FAL charges (3 hours old), from the first generation on."""
    with db.transaction(readonly=True) as tx:
        config = tx.get('config', 'settings')
        key = os.environ.get('FAL_ADMIN_KEY') or config.get('fal_admin_key')
        state = tx.get('cost_sync', 'fal') or {}
    if not key:
        return 0
    start = datetime.fromisoformat(state.get('until', FAL_START))
    settled = datetime.fromtimestamp(now - FAL_SETTLE, timezone.utc).replace(minute=0, second=0, microsecond=0)
    written = 0
    for _ in range(max_windows):
        if start >= settled:
            break
        end = min(start + timedelta(days=1), settled)
        shares = fal_window(get, key, start, end)
        if shares is None:
            break
        with db.transaction() as tx:
            owners = fal_request_items(tx)
            for request_id, endpoint, minute, usd in shares:
                item = owners.get(request_id) if request_id else None
                day = day_of(datetime.fromisoformat(minute + ':00+00:00').timestamp())
                entry = {'id': f'fal:{request_id}' if request_id else f'fal-minute:{endpoint}:{minute}', 'source': 'generation',
                         'order_id': item['order_id'] if item else None, 'organization_id': item.get('organization_id') if item else None,
                         'item_id': item['id'] if item else None, 'request_id': request_id, 'endpoint': endpoint, 'minute': minute,
                         'day': day, 'quantity': 1 if request_id else 0, 'amount_usd': round(usd, 6), 'basis': 'actual'}
                tx.put('cost_entries', entry)
                written += 1
            tx.put('cost_sync', {'id': 'fal', 'until': end.isoformat(), 'synced_at': now})
        start = end
    return written


# Agiso price tiers from its public price list (open.agiso.com/Open/GetApiPriceInfo, 2026-10-16).
AGISO_API_TIERS = {'/aldspdd/trade/detail': 'high', '/aldspdd/goods/list': 'high', '/aldsdoudian/order/detail': 'high',
                   '/aldsdoudian/product/list': 'high', '/aldsdoudian/product/detail': 'high', '/aldsxhs/order/detail': 'high',
                   '/aldsxhs/product/getlist': 'high', '/aldsxhs/product/detail': 'high', '/aldspdd/sys/tokendelete': 'base',
                   '/aldsdoudian/sys/tokendelete': 'base', '/aldsxhs/sys/tokendelete': 'base', '/open/bankroll/querydeposit': 'base'}
# Pushes by platform and aopic; every Pinduoduo push this site receives is "high", so are unlisted ones.
AGISO_PUSH_TIERS = {('douyin', '2'): 'base', ('douyin', '4'): 'base', ('douyin', '8'): 'base', ('xhs', '16'): 'base', ('xhs', '32'): 'base'}


def record_agiso_call(db, api, shop, fields, at):
    """One answered gateway call. Calls about one platform order are charged to it; the rest are shared."""
    from .db import uid
    from .platforms import platform_of
    tier = AGISO_API_TIERS.get(api, 'high')
    number = str(fields.get('tid') or fields.get('shop_order_id') or '')
    with db.transaction() as tx:
        tx.put('cost_entries', {'id': 'agiso-call:' + uid(), 'source': 'agiso', 'api': api, 'tier': tier, 'rate': 'agiso_' + tier,
                                'quantity': 1, 'day': day_of(at), 'shop_id': shop.get('id'), 'organization_id': shop.get('organization_id'),
                                'platform': platform_of(shop), 'order_number': number, 'order_id': None, 'shared': not number})


def agiso_orders_by_number(tx):
    """Platform order id or number -> customer order id (opened orders, then plain order numbers)."""
    found = {o['order_number']: o['id'] for o in tx.all('orders')}
    for link in tx.all('agiso_orders'):
        if link.get('customer_order_id'):
            for key in (link.get('tid'), link.get('order_number')):
                if key:
                    found[str(key)] = link['customer_order_id']
    return found


def sync_agiso(db, now):
    """Push entries (with repeats) and order links for call entries; unmatched ones are shared."""
    from .platforms import platform_of
    with db.transaction() as tx:
        orders = agiso_orders_by_number(tx)
        shops = {s['id']: s for s in tx.all('agiso_shops')}
        repeats = {r['id']: r['count'] for r in tx.all('agiso_push_repeats')}
        for event in tx.all('agiso_events'):
            number = str(event.get('order_number') or event.get('tid') or '')
            shop = shops.get(event.get('shop_id')) or {}
            platform = event.get('platform') or (platform_of(shop) if shop else 'pdd')
            tier = AGISO_PUSH_TIERS.get((platform, str(event.get('topic'))), 'high')
            order_id = orders.get(number)
            entry = {'id': 'agiso-push:' + event['id'], 'source': 'agiso', 'push': f"{platform}:{event.get('topic')}", 'tier': tier,
                     'rate': 'agiso_' + tier, 'quantity': 1 + repeats.get(event['id'], 0), 'day': day_of(event.get('received_at') or now),
                     'shop_id': event.get('shop_id'), 'organization_id': shop.get('organization_id'), 'platform': platform,
                     'order_number': number, 'order_id': order_id, 'shared': not order_id}
            if tx.get('cost_entries', entry['id']) != entry:
                tx.put('cost_entries', entry)
        for entry in tx.find('cost_entries', ("json_extract(doc,'$.source')='agiso' AND json_extract(doc,'$.order_id') IS NULL "
                                              "AND json_extract(doc,'$.order_number')<>''", ())):
            if entry['id'].startswith('agiso-call:') and orders.get(entry['order_number']):
                entry.update(order_id=orders[entry['order_number']], shared=False)
                tx.put('cost_entries', entry)


def query_agiso_deposit(post=None):
    """Open-platform balance (yuan). The query itself is a base-tier call."""
    from .agiso_protocol import settings, sign
    config = settings()
    if not config['app_id'] or not config['secret']:
        return None
    fields = {'appId': config['app_id'], 'timestamp': str(int(time.time()))}
    post = post or (lambda url, **kw: httpx.post(url, timeout=15, **kw))
    response = post('https://gw-api.agiso.com/open/Bankroll/QueryDeposit', data={**fields, 'sign': sign(config['secret'], fields)},
                    headers={'ApiVersion': '1'})
    data = response.json()
    if data.get('IsSuccess') is not True or type(data.get('Data')) not in (int, float):
        raise RuntimeError('deposit query failed')
    return float(data['Data'])


def sync_agiso_deposit(db, now, post=None):
    """One balance snapshot per China day, to calibrate the Agiso unit prices against real deductions."""
    today = day_of(now)
    with db.transaction(readonly=True) as tx:
        if tx.get('agiso_deposit', today):
            return False
    balance = query_agiso_deposit(post)
    if balance is None:
        return False
    with db.transaction() as tx:
        tx.put('agiso_deposit', {'id': today, 'balance': balance, 'at': now})
        tx.put('cost_entries', {'id': 'agiso-call:deposit:' + today, 'source': 'agiso', 'api': '/open/bankroll/querydeposit',
                                'tier': 'base', 'rate': 'agiso_base', 'quantity': 1, 'day': today, 'order_id': None, 'order_number': '', 'shared': True})
    return True


def agiso_calibration(tx, versions, date_from, date_to):
    """Balance drops between daily snapshots against the charges computed for the same days.
    Periods with a top-up (balance going up) are skipped."""
    snapshots = [d for d in tx.all('agiso_deposit') if (not date_from or d['id'] >= date_from) and (not date_to or d['id'] <= date_to)]
    snapshots.sort(key=lambda d: d['id'])
    entries = [e for e in tx.all('cost_entries') if e['source'] == 'agiso']
    drop = computed = 0.0
    days = 0
    for earlier, later in zip(snapshots, snapshots[1:]):
        if later['balance'] > earlier['balance']:
            continue
        drop += earlier['balance'] - later['balance']
        computed += sum(entry_amount(e, versions, None) for e in entries if earlier['id'] <= e['day'] < later['id'])
        days += 1
    latest = snapshots[-1] if snapshots else (max(tx.all('agiso_deposit'), key=lambda d: d['id'], default=None))
    return {'days': days, 'balance_drop': round(drop, 4), 'computed': round(computed, 4),
            'ratio': round(drop / computed, 3) if computed else None, 'balance': latest['balance'] if latest else None,
            'balance_day': latest['id'] if latest else None}


def aliyun_sync(db, now):
    from .aliyun_costs import sync_aliyun
    return sync_aliyun(db, now)


def tick(db, now, get=None):
    """Periodic cost syncs; each source fails on its own without stopping the others.
    `get` replaces outbound HTTP in tests and local browser runs."""
    for name, job in (('fx', lambda: sync_fx(db, now, get)), ('cutout', lambda: sync_cutouts(db)), ('fal', lambda: sync_fal(db, now, get)),
                      ('agiso', lambda: sync_agiso(db, now)), ('agiso-deposit', lambda: None if get else sync_agiso_deposit(db, now)),
                      ('aliyun', lambda: None if get else aliyun_sync(db, now))):  # test runs inject `get`: no balance or bill queries
        try:
            job()
        except Exception as error:
            # Only our own RuntimeError texts are logged (status and error codes); others may hold signed URLs.
            log.warning('Cost sync %s failed (%s); will retry', name,
                        type(error).__name__ + (': ' + str(error)[:120] if type(error) is RuntimeError else ''))


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
    # Shared costs (not tied to one order) are split evenly over every organization's orders of that month, cancelled ones aside.
    month_orders = {}
    for order in tx.all('orders'):
        created = datetime.fromisoformat(order['created_at']).astimezone(zone).date().isoformat()
        if order['state'] != 'cancelled':
            month_orders[created[:7]] = month_orders.get(created[:7], 0) + 1
        if not (global_scope or scoped(order, actor)):
            continue
        if date_from and created < date_from or date_to and created > date_to:
            continue
        if platform and platform_of(order) != platform or shop_id and order.get('shop_id') != shop_id:
            continue
        orders.append((order, created))
    ids = {o['id'] for o, _ in orders}
    by_order, loose, shared = {}, {c: 0.0 for c in CATEGORIES}, {}
    in_range = lambda day: (not date_from or day >= date_from) and (not date_to or day <= date_to)
    for entry in tx.all('cost_entries'):
        if entry.get('order_id') in ids:
            by_order.setdefault(entry['order_id'], []).append(entry)
        elif entry.get('order_id'):
            continue
        elif entry.get('shared') and month_orders.get(entry['day'][:7]):
            key = (entry['day'][:7], entry['source'])
            shared[key] = shared.get(key, 0.0) + entry_amount(entry, versions, fx)
        elif global_scope and in_range(entry['day']):
            # Charges no order can be matched to: tests, requests whose id was not kept, shared costs of a month without orders.
            loose[entry['source']] += entry_amount(entry, versions, fx)
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
        allocated = 0.0
        for c in CATEGORIES:
            share = shared.get((created[:7], c), 0.0) / month_orders[created[:7]] if order['state'] != 'cancelled' and month_orders.get(created[:7]) else 0.0
            costs[c] += share
            allocated += share
        costs = {c: round(v, 4) for c, v in costs.items()}
        for c in CATEGORIES:
            totals[c] += costs[c]
        printed = printed_count(order) if basis else 0
        printed_total += printed
        sheets_total += sheets
        rows.append({'id': order['id'], 'order_number': order['order_number'], 'state': order['state'], 'created': created,
                     'platform': platform_of(order), 'shop_name': shops.get(order.get('shop_id'), ''),
                     'shipped_at': order.get('shipped_at'), 'printed': printed, 'sheets': sheets, 'fixed_basis': basis,
                     'cutouts': counts.get('cutout', 0), 'requests': counts.get('generation', 0), 'allocated': round(allocated, 4), 'costs': costs, 'total': round(sum(costs.values()), 4)})
    rows.sort(key=lambda r: (r['created'], r['order_number']), reverse=True)
    total = round(sum(totals.values()), 4)
    current = fx(today)
    return {'date_from': date_from, 'date_to': date_to, 'today': today, 'scope': 'global' if global_scope else 'organization',
            'rates': rates_on(versions, today), 'rate_versions': versions,
            'fx': {'usd_cny': current['usd_cny'], 'source': current['source'], 'day': current.get('id'), 'published': current.get('published')},
            'summary': {'orders': len(rows), 'printed': printed_total, 'sheets': sheets_total, 'total': total,
                        'per_order': round(total / len(rows), 4) if rows else 0, 'per_sticker': round(total / printed_total, 4) if printed_total else 0,
                        'categories': {c: round(v, 4) for c, v in totals.items()}},
            'orders': rows,
            **({'unattributed': {'categories': {c: round(v, 4) for c, v in loose.items()}, 'total': round(sum(loose.values()), 4)},
                'agiso_check': agiso_calibration(tx, versions, date_from, date_to)} if global_scope else {})}


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
