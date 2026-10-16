"""Per-order cost statistics: fixed costs at shipping, dated rates, cutouts per success, daily USD/CNY."""
import io
import pytest
from PIL import Image
from backend.tests.test_worker import context
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
