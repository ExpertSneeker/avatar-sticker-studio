"""Douyin and Xiaohongshu through mocked Agiso endpoints shaped like docs/agiso-reference examples."""
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
import httpx
from backend.tests.test_agiso import configured, process
from backend.tests.test_worker import context

DOUYIN_ORDER = 4900477063905653860   # beyond 2**53: must stay exact
XHS_ORDER = 'P755073560412360911'


def provider(state):
    def handle(request):
        path = request.url.path
        form = parse_qs(request.content.decode()) if request.content else {}
        state.setdefault('calls', []).append(path)
        if path == '/auth/token':
            platform = 'AldsDoudian' if request.url.host.lower().startswith('aldsdoudian') else 'AldsXhs'
            data = {'FromPlatform': platform, 'UserId': 555, 'ShopName': state.get('name', '测试店'), 'Token': 'private-token', 'ExpiresIn': 86400}
            if platform == 'AldsDoudian':
                data['ShopId'] = 7784061
            return httpx.Response(200, json={'IsSuccess': True, 'Data': data})
        if path == '/aldsDoudian/Order/Detail':
            assert form['shop_order_id'] == [str(DOUYIN_ORDER)]
            body = {'order_id': str(DOUYIN_ORDER), 'order_status': state.get('douyin_status', 2), 'pay_amount': 1990, 'shop_id': 7784061,
                    'buyer_words': '', 'seller_words': state.get('remark', '加急'),
                    'sku_order_list': [{'product_id': 1721288561899563, 'sku_id': 1721288561899566, 'item_num': 2,
                                        'product_name': '头像贴纸', 'spec': [{'name': '规格', 'value': '18张'}]}]}
            return httpx.Response(200, content=json.dumps({'isSuccess': True, 'data': body, 'error_Code': 0}))
        if path == '/aldsDoudian/Product/List':
            return httpx.Response(200, json={'isSuccess': True, 'data': {'data': [{'product_id': 1721288561899563, 'name': '头像贴纸'}], 'total': 1}})
        if path == '/aldsDoudian/Product/Detail':
            return httpx.Response(200, json={'isSuccess': True, 'data': {'name': '头像贴纸', 'spec_prices': [
                {'sku_id': 1721288561899566, 'sell_properties': [{'property_name': '规格', 'value_name': '18张'}]},
                {'sku_id': 1721288561899567, 'sell_properties': [{'property_name': '规格', 'value_name': '6张'}]}]}})
        if path == '/aldsXhs/Order/Detail':
            if state.get('xhs_unreadable'):
                return httpx.Response(200, json={'isSuccess': False, 'error_Code': 1, 'error_Msg': 'no such order'})
            return httpx.Response(200, json={'isSuccess': True, 'data': {'orderId': XHS_ORDER, 'orderStatus': state.get('xhs_status', 4),
                                  'skuList': [{'skuId': 'sku-a', 'skuName': '头像贴纸', 'skuSpec': '12张', 'skuQuantity': 1, 'totalPaidAmount': 2900, 'skuTag': 0},
                                              {'skuId': 'gift', 'skuName': '赠品', 'skuQuantity': 1, 'totalPaidAmount': 0, 'skuTag': 1}]}})
        if path == '/aldsXhs/Product/GetList':
            return httpx.Response(200, json={'isSuccess': True, 'data': {'total': 2, 'data': [
                {'item': {'id': 'item-1', 'name': '头像贴纸'}, 'sku': {'id': 'sku-a', 'itemId': 'item-1', 'variants': [{'name': '规格', 'value': '12张'}]}},
                {'item': {'id': 'item-1', 'name': '头像贴纸'}, 'sku': {'id': 'sku-b', 'itemId': 'item-1', 'variants': [{'name': '规格', 'value': '24张'}]}}]}})
        return httpx.Response(404)
    return handle


def connect(configured, platform, state):
    app, c, _ = configured
    app.state.agiso_worker.transport = httpx.MockTransport(provider(state))
    url = c.post('/api/agiso/authorize', json={'platform': platform}).json()['url']
    query = parse_qs(urlsplit(url.replace('/#/', '/')).query)
    assert c.get('/api/agiso/callback', params={'state': query['state'][0], 'code': 'code'}, follow_redirects=False).headers['location'] == '/?agiso=connected'
    return next(s for s in c.get('/api/agiso/shops').json() if s['platform'] == platform)


def push(c, platform, topic, payload):
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    sign = hashlib.md5(('secretjson' + raw + 'timestamp1000secret').encode()).hexdigest()
    return c.post('/api/agiso/webhook', params={'timestamp': '1000', 'sign': sign, 'aopic': topic, 'fromPlatform': platform}, data={'json': raw})


def drain(app, times=4):
    for _ in range(times):
        process(app)


def events(app, platform):
    with app.state.db.transaction() as tx:
        return [e for e in tx.all('agiso_events') if e.get('platform') == platform]


def test_douyin_connects_imports_skus_and_opens_orders_from_order_detail(configured):
    app, c, _ = configured
    state = {}
    shop = connect(configured, 'douyin', state)
    assert (shop['shop_id'], shop['platform_label']) == ('7784061', '抖店')
    goods = c.get(f"/api/agiso/shops/{shop['id']}/goods").json()
    assert goods['available'] and goods['goods'][0]['skus'] == [{'sku_id': '1721288561899566', 'sku_name': '18张'}, {'sku_id': '1721288561899567', 'sku_name': '6张'}]
    rule = {'goods_id': '1721288561899563', 'sku_id': '1721288561899566', 'goods_name': '头像贴纸', 'sku_name': '18张',
            'generation_limit': 24, 'final_count': 18, 'rerun_limit': 7, 'enabled': True}
    assert c.put(f"/api/agiso/shops/{shop['id']}/rules", json={'rules': [rule]}).status_code == 200
    assert c.patch(f"/api/agiso/shops/{shop['id']}", json={'enabled': True}).status_code == 200
    payment = {'p_id': DOUYIN_ORDER, 's_ids': [], 'shop_id': 7784061, 'order_status': 2, 'order_type': 0, 'pay_amount': 1990}
    assert push(c, 'AldsDoudian', '1', payment).status_code == 200
    assert push(c, 'AldsDoudian', '1', payment).status_code == 200   # duplicate push
    assert push(c, 'AldsDoudian', '16', {'tid': 1}).status_code == 200  # auto-send notice: recorded only
    drain(app)
    orders = c.get('/api/customer-orders').json()
    assert len(orders) == 1
    order = orders[0]
    assert (order['order_number'], order['platform'], order['shop_id']) == (str(DOUYIN_ORDER), 'douyin', shop['id'])
    assert (order['generation_limit'], order['final_count'], order['rerun_limit']) == (48, 36, 7)
    assert order['platform_remark'] == '加急' and order['remark_supported'] and not order['platform_editable']
    assert sorted(e['status'] for e in events(app, 'douyin')) == ['ignored', 'processed']
    # Douyin seller remarks are read back from Order/Detail.
    state['remark'] = '改为普通'
    result = c.post('/api/customer-orders/remarks/sync', json={'ids': [order['id']]}).json()['results'][0]
    assert (result['status'], result['remark']) == ('updated', '改为普通')


def test_douyin_refunds_wait_until_douyin_aftersales_is_verified(configured, monkeypatch):
    app, c, _ = configured
    shop = connect(configured, 'douyin', {})
    rule = {'goods_id': '1721288561899563', 'sku_id': '1721288561899566', 'generation_limit': 10, 'final_count': 10, 'rerun_limit': 1, 'enabled': True}
    c.put(f"/api/agiso/shops/{shop['id']}/rules", json={'rules': [rule]}); c.patch(f"/api/agiso/shops/{shop['id']}", json={'enabled': True})
    push(c, 'AldsDoudian', '1', {'p_id': DOUYIN_ORDER, 'shop_id': 7784061, 'pay_amount': 1990}); drain(app)
    order = c.get('/api/customer-orders').json()[0]
    refund = {'aftersale_id': 7000893114000949000, 'aftersale_type': 2, 'apply_time': 1630022518, 'p_id': DOUYIN_ORDER,
              's_id': DOUYIN_ORDER, 'refund_amount': 1990, 'shop_id': 7784061}
    push(c, 'AldsDoudian', '2', refund); drain(app)
    # Only Pinduoduo refunds are verified in this fixture: the Douyin fact is kept, the order stays usable.
    assert [e['error'] for e in events(app, 'douyin') if e['family'] == 'refund'] == ['aftersales_disabled']
    assert not c.get('/api/customer-orders/' + order['id']).json()['paused']
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_PLATFORMS', 'pdd,douyin')
    drain(app)
    assert c.get('/api/customer-orders/' + order['id']).json()['paused']
    push(c, 'AldsDoudian', '8', {**refund, 'success_time': 1630022600}); drain(app)
    assert c.get('/api/customer-orders/' + order['id']).json()['state'] == 'cancelled'


def test_xiaohongshu_matches_skus_only_and_finds_its_shop_by_order(configured):
    app, c, _ = configured
    state = {}
    shop = connect(configured, 'xhs', state)
    assert shop['shop_id'] == '555'   # token carried only UserId
    goods = c.get(f"/api/agiso/shops/{shop['id']}/goods").json()['goods']
    assert goods == [{'goods_id': 'item-1', 'goods_name': '头像贴纸', 'skus': [{'sku_id': 'sku-a', 'sku_name': '12张'}, {'sku_id': 'sku-b', 'sku_name': '24张'}]}]
    rule = {'goods_id': 'item-1', 'sku_id': 'sku-a', 'goods_name': '头像贴纸', 'sku_name': '12张', 'generation_limit': 16, 'final_count': 12, 'rerun_limit': 6, 'enabled': True}
    c.put(f"/api/agiso/shops/{shop['id']}/rules", json={'rules': [rule]}); c.patch(f"/api/agiso/shops/{shop['id']}", json={'enabled': True})
    # The push names the shop by its Xiaohongshu seller id, which the token did not include.
    payment = {'sellerId': '64f196de9bac760001e6de2x', 'orderId': XHS_ORDER, 'orderStatus': 4, 'updateTime': 1740041385334}
    assert push(c, 'AldsXhs', '4', payment).status_code == 200
    assert [e['status'] for e in events(app, 'xhs')] == ['unmatched']
    drain(app)
    order = c.get('/api/customer-orders').json()[0]
    assert (order['order_number'], order['platform'], order['final_count'], order['remark_supported']) == (XHS_ORDER, 'xhs', 12, False)
    with app.state.db.transaction() as tx:
        assert tx.get('agiso_shops', shop['id'])['push_keys'] == ['64f196de9bac760001e6de2x']
    # The remembered seller id routes later pushes directly; a refund request is recorded for the shop.
    push(c, 'AldsXhs', '16', {'sellerId': '64f196de9bac760001e6de2x', 'returnsId': 'r1', 'orderId': XHS_ORDER, 'returnType': 3, 'refundFee': 29, 'updateTime': 1740041385335})
    assert next(e for e in events(app, 'xhs') if e['family'] == 'refund')['shop_id'] == shop['id']


def test_unreadable_or_unpaid_platform_orders_never_open(configured):
    app, c, _ = configured
    state = {'xhs_unreadable': True}
    shop = connect(configured, 'xhs', state)
    rule = {'goods_id': 'item-1', 'sku_id': 'sku-a', 'generation_limit': 16, 'final_count': 12, 'rerun_limit': 6, 'enabled': True}
    c.put(f"/api/agiso/shops/{shop['id']}/rules", json={'rules': [rule]}); c.patch(f"/api/agiso/shops/{shop['id']}", json={'enabled': True})
    push(c, 'AldsXhs', '4', {'sellerId': '555', 'orderId': XHS_ORDER, 'orderStatus': 4, 'updateTime': 1})
    clock = app.state.clock
    for _ in range(6):
        process(app); clock.value += 400
    assert [(e['status'], e['error']) for e in events(app, 'xhs')] == [('manual', 'order_lookup_failed')]
    state['xhs_unreadable'] = False; state['xhs_status'] = 9
    push(c, 'AldsXhs', '4', {'sellerId': '555', 'orderId': XHS_ORDER, 'orderStatus': 9, 'updateTime': 2}); drain(app)
    assert c.get('/api/customer-orders').json() == []
    with app.state.db.transaction() as tx:
        assert [link['error'] for link in tx.all('agiso_orders')] == ['order_cancelled']


def test_order_numbers_stay_unique_across_platforms(configured):
    app, c, _ = configured
    assert c.post('/api/customer-orders', json={'platform': 'pdd', 'order_number': XHS_ORDER, 'generation_limit': 2, 'final_count': 1, 'rerun_limit': 0, 'client_token': 'manual'}).status_code == 200
    shop = connect(configured, 'xhs', {})
    rule = {'goods_id': 'item-1', 'sku_id': 'sku-a', 'generation_limit': 16, 'final_count': 12, 'rerun_limit': 6, 'enabled': True}
    c.put(f"/api/agiso/shops/{shop['id']}/rules", json={'rules': [rule]}); c.patch(f"/api/agiso/shops/{shop['id']}", json={'enabled': True})
    push(c, 'AldsXhs', '4', {'sellerId': '555', 'orderId': XHS_ORDER, 'orderStatus': 4, 'updateTime': 1}); drain(app)
    assert len(c.get('/api/customer-orders').json()) == 1
    with app.state.db.transaction() as tx:
        assert [link['error'] for link in tx.all('agiso_orders')] == ['order_number_conflict']
