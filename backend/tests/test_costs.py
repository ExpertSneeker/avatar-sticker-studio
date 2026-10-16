"""Per-order cost statistics: fixed costs at shipping, dated rates, cutouts per success, daily USD/CNY."""
import io
import pytest
from PIL import Image
from backend.tests.test_worker import context
from backend.tests.test_agiso import configured
from backend.tests.test_api import upload
from backend.tests.test_mixed_stickers import sticker
from backend.tests.test_customer_orders import action, opened, run
from backend.tests.test_customer_designs import cutouts, design_order, send
from backend.tests.helpers import member, order_items
from backend.app import costs

DAY = 86400


def printed(app, c, number, sid, count):
    o = opened(c, number, generation_limit=count, final_count=count)
    o = action(c, o, 'generate', avatars=[{'upload_id': upload(c)['id'], 'template_ids': [], 'sticker_ids': [sid] * count}]).json()
    run(app)
    o = c.get('/api/customer-orders/'+o['id']).json()
    o = action(c, o, 'submit', slot_ids=[s['id'] for s in o['slots']]).json()
    app.state.worker.publish(o['id'])
    return c.get('/api/customer-orders/'+o['id']).json()


def report(c, **params):
    response = c.get('/api/costs', params={'scope': 'global', **params})
    assert response.status_code == 200, response.text
    return response.json()


def row(data, number):
    return next(r for r in data['orders'] if r['order_number'] == number)


def test_fixed_costs_follow_shipping_with_dated_rates(context):
    app, c, clock, _ = context
    today = costs.day_of(clock.value)
    sid = sticker(c, 'ONE')['id']
    one, seven = printed(app, c, 'COST-1', sid, 1), printed(app, c, 'COST-7', sid, 7)
    draft = opened(c, 'COST-D')
    data = report(c)
    # Submitted, not shipped yet: packaging, shipping and sheets are estimated.
    assert row(data, 'COST-1')['fixed_basis'] == 'estimate' and row(data, 'COST-1')['costs']['packaging'] == 0.3
    assert row(data, 'COST-D')['total'] == 0 and row(data, 'COST-D')['fixed_basis'] is None
    action(c, one, 'ship'); action(c, seven, 'ship')
    data = report(c)
    r1, r7 = row(data, 'COST-1'), row(data, 'COST-7')
    assert r1['fixed_basis'] == 'actual' and (r1['printed'], r1['sheets']) == (1, 1)  # one sticker still takes a sheet
    assert (r7['printed'], r7['sheets']) == (7, 2)  # six per sheet
    assert r1['costs']['packaging'] == 0.3 and r1['costs']['shipping'] == 2.3 and r1['costs']['material'] == 0.27
    assert r7['costs']['material'] == pytest.approx(0.54)
    assert data['summary']['printed'] == 8 and data['summary']['sheets'] == 3
    assert data['summary']['total'] == pytest.approx(r1['total'] + r7['total'])
    assert data['summary']['per_sticker'] == pytest.approx(data['summary']['total'] / 8, abs=1e-4)
    # A new rate from tomorrow leaves orders shipped today unchanged; one from today applies to them.
    tomorrow = costs.day_of(clock.value + DAY)
    rates = {**costs.DEFAULT_RATES, 'from': tomorrow, 'shipping': 3.0}
    assert c.put('/api/costs/rates', json=rates).status_code == 200
    assert row(report(c), 'COST-1')['costs']['shipping'] == 2.3
    c.put('/api/costs/rates', json={**rates, 'from': today})
    data = report(c)
    assert row(data, 'COST-1')['costs']['shipping'] == 3.0 and [v['from'] for v in data['rate_versions']] == sorted({costs.DEFAULT_RATES['from'], today, tomorrow})
    assert c.put('/api/costs/rates', json={**rates, 'per_sheet': 0}).status_code == 422
    # Date filters use the China day the order was opened.
    assert report(c, date_from=tomorrow)['orders'] == [] and len(report(c, date_to=today)['orders']) == 3
    # Only administrators see costs, and only platform administrators edit rates or see every organization.
    staff, _ = member(c, app)
    assert staff.get('/api/costs').status_code == 403
    assert staff.put('/api/costs/rates', json=rates).status_code == 403
    assert c.get('/api/costs').status_code == 200


def test_cutouts_are_charged_per_success_and_inferred_for_older_items(context, cutouts):
    app, c, clock, _ = context
    o = design_order(c); run(app); run(app)
    see_through = Image.new('RGBA', (300, 300), (0, 0, 0, 0)); see_through.paste((200, 40, 40, 255), (50, 50, 250, 250))
    out = io.BytesIO(); see_through.save(out, 'PNG')
    clear = send(c, out.getvalue(), name='透明.png')
    t = opened(c, 'COST-T', generation_limit=1, final_count=1)
    t = action(c, t, 'generate', designs=[{'upload_id': clear['id']}]).json(); run(app)
    assert cutouts.calls == 2
    # An item from before `cutout_used` was recorded: the opaque original proves a cutout.
    item = order_items(app, o)[0]
    with app.state.db.transaction() as tx:
        legacy = tx.get('items', item['id']); legacy.pop('cutout_used'); tx.put('items', legacy)
    assert costs.sync_cutouts(app.state.db) == 3 and costs.sync_cutouts(app.state.db) == 0
    with app.state.db.transaction() as tx:
        entries = {e['item_id']: e for e in tx.all('cost_entries')}
    assert entries[item['id']]['quantity'] == 1 and entries[item['id']]['basis'] == 'inferred'
    assert sum(e['quantity'] for e in entries.values()) == 2
    data = report(c)
    r = next(r for r in data['orders'] if r['id'] == o['id'])
    assert r['cutouts'] == 2 and r['costs']['cutout'] == pytest.approx(0.064)
    assert row(data, 'COST-T')['costs']['cutout'] == 0


class Answer:
    def __init__(self, value): self.value = value
    def json(self):
        if isinstance(self.value, Exception): raise self.value
        return self.value


def test_daily_exchange_rate_prefers_cfets_and_falls_back(context):
    app, c, clock, _ = context
    db = app.state.db
    d0, d1, d2 = (costs.day_of(clock.value + n * DAY) for n in range(3))
    with db.transaction(readonly=True) as tx:
        assert costs.fx_on(tx, d0)['source'] == 'fallback'
    calls = []
    def cfets(url):
        calls.append(url)
        return Answer({'data': {'lastDate': '2026-10-15 9:15'}, 'records': [{'vrtEName': 'EUR/CNY', 'price': '7.9'}, {'vrtEName': 'USD/CNY', 'price': '6.7220'}]})
    assert costs.sync_fx(db, clock.value, cfets) and not costs.sync_fx(db, clock.value + 60, cfets)
    assert len(calls) == 1
    def broken_then_backup(url):
        if 'chinamoney' in url: raise ValueError('down')
        return Answer({'rates': {'CNY': 6.70}, 'time_last_update_utc': 'x'})
    assert costs.sync_fx(db, clock.value + DAY, broken_then_backup)
    def down(url): raise ValueError('down')
    with pytest.raises(ValueError):
        costs.sync_fx(db, clock.value + 2 * DAY, down)
    assert not costs.sync_fx(db, clock.value + 2 * DAY + 60, cfets)  # retried hourly, not every minute
    assert costs.sync_fx(db, clock.value + 2 * DAY + 3601, cfets)
    with db.transaction(readonly=True) as tx:
        assert costs.fx_on(tx, d0)['usd_cny'] == 6.722 and costs.fx_on(tx, d1)['source'] == 'open.er-api.com'
        assert costs.fx_on(tx, '2999-01-01')['id'] == d2 and costs.fx_on(tx, '1960-01-01')['id'] == d0
    assert report(c)['fx']['usd_cny'] == 6.722 and report(c)['fx']['day'] == d0


class FakeFal:
    """FAL usage (minute and hour) and request listing for one window; records what was asked."""
    def __init__(self, minutes, requests, hour_total=None):
        self.minutes, self.requests, self.calls = minutes, requests, []
        self.hour_total = sum(c for _, _, c in minutes) if hour_total is None else hour_total
    def __call__(self, url, params=None, headers=None):
        assert headers == {'Authorization': 'Key fal-admin-test'}
        self.calls.append((url, dict(params)))
        if url.endswith('/usage') and params['timeframe'] == 'minute':
            series = [{'bucket': m + ':00+00:00', 'results': [{'endpoint_id': e, 'cost': c}]} for e, m, c in self.minutes]
            return Answer({'time_series': series, 'has_more': False})
        if url.endswith('/usage'):
            return Answer({'time_series': [{'bucket': '2026-09-01T00:00:00+00:00', 'results': [{'endpoint_id': 'x', 'cost': self.hour_total}]}], 'has_more': False})
        items = [r for r in self.requests if r['endpoint_id'] == params['endpoint_id']]
        return Answer({'items': items, 'has_more': False})


def test_fal_charges_are_split_per_request_and_unmatched_ones_stay_unattributed(context):
    from datetime import datetime, timezone
    app, c, clock, _ = context
    sid = sticker(c, 'ONE')['id']
    a, b = printed(app, c, 'FAL-A', sid, 1), printed(app, c, 'FAL-B', sid, 1)
    with app.state.db.transaction() as tx:
        config = tx.get('config', 'settings'); config['fal_admin_key'] = 'fal-admin-test'; tx.put('config', config)
        ia, ib = order_items(app, a)[0], order_items(app, b)[0]
        ia.update(fal_request_id='ra'); tx.put('items', ia)
        ib.update(fal_request_id='rb', fal_request_ids=['rb-old', 'rb']); tx.put('items', ib)
    ep = 'openai/gpt-image-2.5/flare/edit'
    req = lambda rid, minute, status=200: {'request_id': rid, 'endpoint_id': ep, 'status_code': status, 'ended_at': minute + ':41.2Z'}
    fake = FakeFal([(ep, '2026-09-01T01:05', 0.0556), (ep, '2026-09-01T01:30', 0.0278), (ep, '2026-09-01T02:00', 0.01), (ep, '2026-09-01T02:10', 0.03)],
                   [req('ra', '2026-09-01T01:05'), req('rb-old', '2026-09-01T01:05'), req('rb', '2026-09-01T01:30'),
                    req('refused', '2026-09-01T01:30', 422), req('stranger', '2026-09-01T02:10'), req('free', '2026-09-01T02:40')])
    now = datetime(2026, 9, 1, 6, 20, tzinfo=timezone.utc).timestamp()
    # Not configured: nothing is asked.
    with app.state.db.transaction() as tx:
        config = tx.get('config', 'settings'); key = config.pop('fal_admin_key'); tx.put('config', config)
    assert costs.sync_fal(app.state.db, now, fake) == 0 and fake.calls == []
    with app.state.db.transaction() as tx:
        config = tx.get('config', 'settings'); config['fal_admin_key'] = key; tx.put('config', config)
    # Totals that disagree (data still settling) are not booked and the window is retried.
    wrong = FakeFal(fake.minutes, fake.requests, hour_total=1.0)
    assert costs.sync_fal(app.state.db, now, wrong) == 0
    assert costs.sync_fal(app.state.db, now, fake) == 5
    assert costs.sync_fal(app.state.db, now, fake) == 0  # settled up to 03:00 already
    with app.state.db.transaction() as tx:
        entries = {e['id']: e for e in tx.all('cost_entries') if e['source'] == 'generation'}
        assert tx.get('cost_sync', 'fal')['until'] == '2026-09-01T03:00:00+00:00'
    assert entries['fal:ra']['amount_usd'] == pytest.approx(0.0278) and entries['fal:ra']['order_id'] == a['id']
    assert entries['fal:rb-old']['order_id'] == b['id'] and entries['fal:rb']['amount_usd'] == pytest.approx(0.0278)
    assert 'fal:refused' not in entries and 'fal:free' not in entries  # failed or not charged
    assert entries['fal:stranger']['order_id'] is None and entries['fal-minute:' + ep + ':2026-09-01T02:00']['amount_usd'] == 0.01
    assert entries['fal:ra']['day'] == '2026-09-01'
    with app.state.db.transaction() as tx:
        tx.put('fx_rates', {'id': '2026-09-01', 'usd_cny': 7.0, 'source': 'cfets'})
    data = report(c)
    assert row(data, 'FAL-A')['costs']['generation'] == pytest.approx(0.0278 * 7, abs=1e-4)
    assert row(data, 'FAL-B')['costs']['generation'] == pytest.approx(0.0556 * 7, abs=1e-4) and row(data, 'FAL-B')['requests'] == 2
    assert data['unattributed']['categories']['generation'] == pytest.approx(0.04 * 7, abs=1e-4)
    assert 'unattributed' not in c.get('/api/costs').json()


def test_agiso_pushes_with_repeats_and_calls_are_charged_and_unmatched_ones_shared(configured):
    from backend.tests.test_agiso import shop, trade, push, process, refund
    app, c, clock = configured
    s = shop(configured)
    assert push(c, trade('AG-1')).status_code == 200; process(app)
    push(c, trade('AG-1'))  # Agiso sent it again: charged again, stored once
    push(c, refund('GHOST', 'R9'), topic='8')  # a refund for an order this site never opened
    o = c.get('/api/customer-orders').json()[0]
    assert c.get('/api/agiso/shops/'+s['id']+'/goods').status_code == 200  # shop-level call
    assert c.post('/api/customer-orders/remarks/sync', json={'ids': [o['id']]}).status_code == 200  # Trade/Detail for this order
    costs.sync_agiso(app.state.db, clock())
    with app.state.db.transaction() as tx:
        entries = [e for e in tx.all('cost_entries') if e['source'] == 'agiso']
    pushes = {e['order_number']: e for e in entries if 'push' in e}
    calls = {e['api']: e for e in entries if 'api' in e}
    assert pushes['AG-1']['quantity'] == 2 and pushes['AG-1']['order_id'] == o['id'] and pushes['AG-1']['tier'] == 'high'
    assert pushes['GHOST']['order_id'] is None and pushes['GHOST']['shared']
    assert calls['/aldspdd/goods/list']['shared'] and calls['/aldspdd/goods/list']['rate'] == 'agiso_high'
    assert calls['/aldspdd/trade/detail']['order_id'] == o['id'] and not calls['/aldspdd/trade/detail']['shared']
    costs.sync_agiso(app.state.db, clock())  # idempotent
    with app.state.db.transaction() as tx:
        assert len([e for e in tx.all('cost_entries') if e['source'] == 'agiso']) == len(entries)
    # The order carries its own pushes and calls plus this month's shared Agiso costs (it is the only order).
    data = report(c)
    r = row(data, o['order_number'])
    assert r['costs']['agiso'] == pytest.approx(3 * 0.002 + 2 * 0.002) and r['allocated'] == pytest.approx(0.004)
    assert data['unattributed']['categories']['agiso'] == 0
    # Daily balance snapshots calibrate the unit prices against what Agiso actually deducted.
    class Balance:
        def __init__(self, value): self.value = value
        def json(self): return {'IsSuccess': True, 'Data': self.value}
    assert costs.sync_agiso_deposit(app.state.db, clock(), lambda url, **kw: Balance(4.343))
    assert not costs.sync_agiso_deposit(app.state.db, clock() + 60, lambda url, **kw: Balance(1.0))
    assert costs.sync_agiso_deposit(app.state.db, clock() + DAY, lambda url, **kw: Balance(4.333))
    check = report(c)['agiso_check']
    assert check['balance'] == 4.333 and check['days'] == 1 and check['balance_drop'] == pytest.approx(0.01)
    assert check['computed'] == pytest.approx(0.011) and check['ratio'] == pytest.approx(0.01 / 0.011, abs=1e-3)


class FakeAliyun:
    region, site_id = 'cn-wulanchabu', 'site'
    def __init__(self, lines, rows, ready=True):
        self.lines, self.rows, self.ready = lines, rows, ready
    def bill(self, day, product):
        if product == 'oss':
            return [('cn-wulanchabu;standard-zrs', '外网流出流量', 'PayAsYouGo', 0.5), ('cn-wulanchabu;standard-zrs', '标准存储（同城冗余）容量', 'PayAsYouGo', 0.03),
                    ('cn-beijing;standard', '外网流出流量', 'PayAsYouGo', 9.0)] if self.ready else []
        return [('esa-site', '流量', 'PayAsYouGo', 0.02)] if product == 'dcdn' else []
    def subscriptions(self, cycle, product):
        return [(51.1, 12)]
    def oss_lines(self, day):
        return self.lines
    def esa_rows(self, day):
        return self.rows


def test_oss_and_esa_days_are_split_by_bytes_and_the_rest_shared(context):
    from datetime import datetime, timezone
    from backend.app import aliyun_costs
    app, c, clock, _ = context
    sid = sticker(c, 'ONE')['id']
    a, b = printed(app, c, 'NET-A', sid, 1), printed(app, c, 'NET-B', sid, 1)
    with app.state.db.transaction() as tx:
        item = order_items(app, a)[0]
        started = datetime.fromtimestamp(item['started_at'], timezone.utc)
        template_sha = tx.get('assets', item['template_id'])['sha256']
        asset = next(x for x in tx.all('assets') if x.get('order_id') == b['id'])
    day = started.astimezone(aliyun_costs.CHINA).date().isoformat()
    stamp = started.astimezone(aliyun_costs.CHINA).strftime('%d/%b/%Y:%H:%M:%S +0800')
    def line(path, sent, host='coreages-sticker.oss-cn-wulanchabu.aliyuncs.com', method='GET'):
        return f'1.2.3.4 - - [{stamp}] "{method} /{path} HTTP/1.1" 200 {sent} 10 "-" "ua" "{host}" "rid" "true" "-" "GetObject" "coreages-sticker" "-" - 0 "-" 1 "1" - "-" "standard" "-" "-" "-" "-" - -'
    lines = [line(f"print/org/{b['id']}/x.png", 600),
             line(f"fal-inputs/{started:%Y%m%d}/{template_sha}.png", 300),  # used by both orders' items that day
             line('fal-inputs/20990101/' + 'f' * 64 + '.png', 100),            # unknown input: shared
             line(f"backups/x.tar", 999999, host='coreages-sticker.oss-cn-wulanchabu-internal.aliyuncs.com')]  # internal: free
    rows = [{'ClientRequestHost': 'sticker.coreages.com', 'ClientIP': '9.9.9.9', 'ClientRequestURI': f"/api/guest/media/{a['id']}/x?m=1", 'EdgeResponseBytes': 1000},
            {'ClientRequestHost': 'sticker.coreages.com', 'ClientIP': '9.9.9.9', 'ClientRequestURI': '/media/catalog/x/y/1/z.webp', 'EdgeResponseBytes': 500},
            {'ClientRequestHost': 'sticker.coreages.com', 'ClientIP': '8.8.8.8', 'ClientRequestURI': f"/api/assets/{asset['id']}", 'EdgeResponseBytes': 1500},
            {'ClientRequestHost': 'sticker.coreages.com', 'ClientIP': '8.8.8.8', 'ClientRequestURI': '/api/stickers', 'EdgeResponseBytes': 2000},
            {'ClientRequestHost': 'www.coreages.com', 'ClientIP': '7.7.7.7', 'ClientRequestURI': '/', 'EdgeResponseBytes': 99999}]
    assert aliyun_costs.sync_day(app.state.db, FakeAliyun(lines, rows, ready=False), day) is False
    assert aliyun_costs.sync_day(app.state.db, FakeAliyun(lines, rows), day)
    assert aliyun_costs.sync_day(app.state.db, FakeAliyun(lines, rows), day)  # re-syncing a day replaces it
    with app.state.db.transaction() as tx:
        entries = {e['id']: e for e in tx.all('cost_entries') if e['source'] in ('oss', 'esa')}
    # OSS traffic 0.5 over 1000 public bytes: B 600 + 150, A 150, unknown input 100 shared; storage shared.
    assert entries[f"oss:{day}:{b['id']}"]['amount_cny'] == pytest.approx(0.5 * 750 / 1000)
    assert entries[f"oss:{day}:{a['id']}"]['amount_cny'] == pytest.approx(0.5 * 150 / 1000)
    assert entries[f'oss:{day}:shared']['amount_cny'] == pytest.approx(0.05) and entries[f'oss-storage:{day}']['amount_cny'] == 0.03
    # ESA: plan 51.1 over 365 days plus 0.02 pay-as-you-go, over 5000 sticker bytes.
    esa = 51.1 / 365 + 0.02
    assert entries[f"esa:{day}:{a['id']}"]['amount_cny'] == pytest.approx(esa * 1500 / 5000)  # media + catalog by IP
    assert entries[f"esa:{day}:{b['id']}"]['amount_cny'] == pytest.approx(esa * 1500 / 5000)  # its print asset
    assert entries[f'esa:{day}:shared']['amount_cny'] == pytest.approx(esa * 2000 / 5000) and entries[f'esa:{day}:shared']['shared']
    # Shared parts are spread over the month's two orders.
    data = report(c)
    shared = (0.05 + 0.03) / 2
    assert row(data, 'NET-A')['costs']['oss'] == pytest.approx(0.5 * 150 / 1000 + shared, abs=1e-4)
    assert row(data, 'NET-B')['costs']['esa'] == pytest.approx(esa * 0.3 + esa * 0.4 / 2, abs=1e-4)
    # Not configured: nothing happens; days are taken oldest first, two days back at most.
    assert aliyun_costs.sync_aliyun(app.state.db, clock(), None) == 0
