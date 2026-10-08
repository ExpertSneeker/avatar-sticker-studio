"""Multi-platform foundation: platform/shop on orders, shop watermarks, platform-aware Agiso boundaries."""
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.platforms import migrate_platforms
from backend.tests.test_agiso import configured, shop, trade, push, process
from backend.tests.test_worker import context


def manual(c, number, **fields):
    return c.post('/api/customer-orders', json={'order_number': number, 'generation_limit': 2, 'final_count': 1,
                                                'rerun_limit': 0, 'client_token': number, **fields})


def test_manual_orders_require_platform_and_take_the_shop_watermark(configured):
    app, c, _ = configured
    s = shop(configured)
    assert manual(c, 'NO-PLATFORM').status_code == 422
    assert manual(c, 'BAD-PLATFORM', platform='taobao').status_code == 422
    # A shop must belong to the chosen platform and organization.
    assert manual(c, 'WRONG-SHOP', platform='douyin', shop_id=s['id']).status_code == 422
    assert manual(c, 'GHOST-SHOP', platform='pdd', shop_id='missing').status_code == 422
    assert c.put('/api/agiso/shops/' + s['id'] + '/watermark', json={'watermark': '  草木造物  '}).json()['watermark'] == '草木造物'
    with_shop = manual(c, 'WITH-SHOP', platform='pdd', shop_id=s['id']).json()
    assert (with_shop['platform'], with_shop['shop_id'], with_shop['watermark']) == ('pdd', s['id'], '草木造物')
    without = manual(c, 'NO-SHOP', platform='xhs').json()
    assert (without['platform'], without['shop_id'], without['watermark']) == ('xhs', None, '管理员')
    assert c.put('/api/agiso/shops/' + s['id'] + '/watermark', json={'watermark': '   '}).status_code == 422


def test_auto_opened_orders_use_the_shop_watermark_and_platform(configured):
    app, c, _ = configured
    s = shop(configured)
    assert s['platform'] == 'pdd' and s['platform_label'] == '拼多多' and s['watermark'] == '管理员'
    c.put('/api/agiso/shops/' + s['id'] + '/watermark', json={'watermark': '云上的创意'})
    push(c, trade('SHOP-MARK')); process(app)
    order = c.get('/api/customer-orders').json()[0]
    assert (order['platform'], order['shop_id'], order['watermark'], order['platform_editable']) == ('pdd', s['id'], '云上的创意', False)


def test_changing_a_shop_watermark_only_reaches_old_orders_through_the_batch_update(configured):
    app, c, _ = configured
    s = shop(configured)
    old = manual(c, 'OLD', platform='pdd', shop_id=s['id']).json()
    c.put('/api/agiso/shops/' + s['id'] + '/watermark', json={'watermark': '新水印'})
    assert c.get('/api/customer-orders/' + old['id']).json()['watermark'] == '管理员'
    preview = c.post('/api/customer-orders/watermarks/preview', json={'ids': [old['id']]}).json()
    assert preview['orders'][0]['watermark'] == '新水印'
    applied = c.post('/api/customer-orders/watermarks', json={'ids': [old['id']], 'preview_token': preview['preview_token'], 'client_token': 'wm'})
    assert applied.status_code == 200
    assert c.get('/api/customer-orders/' + old['id']).json()['watermark'] == '新水印'


def test_manual_orders_can_change_platform_but_agiso_orders_cannot(configured):
    app, c, _ = configured
    s = shop(configured)
    order = manual(c, 'MOVE', platform='xhs').json()
    body = {'client_token': 'move', 'expected_version': order['version'], 'platform': 'pdd', 'shop_id': s['id']}
    moved = c.post(f"/api/customer-orders/{order['id']}/platform", json=body)
    assert moved.status_code == 200 and (moved.json()['platform'], moved.json()['shop_id']) == ('pdd', s['id'])
    # The watermark snapshot is not rewritten by a platform change.
    assert moved.json()['watermark'] == order['watermark']
    assert c.post(f"/api/customer-orders/{order['id']}/platform", json=body).json()['version'] == moved.json()['version']
    stale = {**body, 'client_token': 'stale', 'platform': 'douyin', 'shop_id': None}
    assert c.post(f"/api/customer-orders/{order['id']}/platform", json=stale).status_code == 409
    wrong = {'client_token': 'wrong', 'expected_version': moved.json()['version'], 'platform': 'douyin', 'shop_id': s['id']}
    assert c.post(f"/api/customer-orders/{order['id']}/platform", json=wrong).status_code == 422
    push(c, trade('LINKED')); process(app)
    linked = next(o for o in c.get('/api/customer-orders').json() if o['order_number'] == 'LINKED')
    attempt = {'client_token': 'linked', 'expected_version': linked['version'], 'platform': 'xhs', 'shop_id': None}
    assert c.post(f"/api/customer-orders/{linked['id']}/platform", json=attempt).status_code == 409


def test_only_connected_platforms_authorize_or_push(configured):
    app, c, _ = configured
    assert c.post('/api/agiso/authorize', json={'platform': 'douyin'}).status_code == 409
    assert c.post('/api/agiso/authorize', json={'platform': 'taobao'}).status_code == 409
    url = c.post('/api/agiso/authorize', json={'platform': 'pdd'}).json()['url']
    assert url.startswith('https://aldspdd.agiso.com/#/authorize?')
    platforms = {p['key']: p for p in c.get('/api/agiso/status').json()['platforms']}
    assert platforms['pdd']['connectable'] and not platforms['douyin']['connectable'] and not platforms['xhs']['connectable']
    raw = json.dumps({'p_id': 1}, separators=(',', ':'))
    sign = hashlib.md5(('secretjson' + raw + 'timestamp1000secret').encode()).hexdigest()
    refused = c.post('/api/agiso/webhook', params={'timestamp': '1000', 'sign': sign, 'aopic': '1', 'fromPlatform': 'AldsDoudian'}, data={'json': raw})
    assert refused.status_code == 422


def test_shop_identity_includes_the_platform(configured):
    app, c, _ = configured
    s = shop(configured)
    # A Douyin shop that happens to share the Pinduoduo shop id must not receive Pinduoduo pushes.
    with app.state.db.transaction() as tx:
        twin = {**tx.get('agiso_shops', s['id']), 'id': 'twin', 'platform': 'douyin', 'rules': []}
        tx.put('agiso_shops', twin)
    push(c, trade('ROUTED')); process(app)
    order = c.get('/api/customer-orders').json()[0]
    assert order['shop_id'] == s['id']
    with app.state.db.transaction() as tx:
        event = next(e for e in tx.all('agiso_events') if e['order_number'] == 'ROUTED')
    assert event['platform'] == 'pdd' and event['shop_id'] == s['id']


def test_aftersales_is_verified_per_platform(monkeypatch):
    from backend.app.agiso_protocol import aftersales_platforms, aftersales_for
    monkeypatch.delenv('STUDIO_AGISO_AFTERSALES_PLATFORMS', raising=False)
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_VERIFIED', '1')
    assert aftersales_platforms() == {'pdd'}
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_PLATFORMS', 'pdd, douyin, taobao')
    assert aftersales_platforms() == {'pdd', 'douyin'}
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_PLATFORMS', '')
    assert aftersales_platforms() == set()
    config = {'aftersales_platforms': frozenset({'douyin'})}
    assert aftersales_for(config, {'platform': 'douyin'}) and not aftersales_for(config, {}) and not aftersales_for(config, None)


def test_platform_migration_marks_everything_pinduoduo_and_copies_owner_watermarks(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app, client=('127.0.0.1', 1)) as c:
        assert c.post('/api/auth/setup', json={'username': 'magnus', 'password': 'safe-password-123', 'display_name': 'Magnux'}).status_code == 200
    db = app.state.db
    with db.transaction() as tx:
        owner = next(u for u in tx.all('users'))
        owner['watermark'] = '草木造物'; tx.put('users', owner)
        tx.put('agiso_shops', {'id': 's1', 'shop_id': '999', 'shop_name': '草木造物', 'owner': owner['id'], 'organization_id': owner['organization_id'], 'rules': []})
        tx.put('agiso_orders', {'id': 'l1', 'shop_id': 's1', 'tid': 'T1'})
        tx.put('agiso_events', {'id': 'e1', 'shop_id': 's1', 'status': 'processed'})
        tx.put('orders', {'id': 'o1', 'agiso_id': 'l1', 'watermark': 'Magnux', 'organization_id': owner['organization_id']})
        tx.put('orders', {'id': 'o2', 'watermark': 'Magnux', 'organization_id': owner['organization_id']})
        tx.delete('migrations', 'platform-v1')
        migrate_platforms(tx)
        migrate_platforms(tx)
        shop_row = tx.get('agiso_shops', 's1')
        assert (shop_row['platform'], shop_row['watermark']) == ('pdd', '草木造物')
        assert tx.get('agiso_orders', 'l1')['platform'] == 'pdd' and tx.get('agiso_events', 'e1')['platform'] == 'pdd'
        assert (tx.get('orders', 'o1')['platform'], tx.get('orders', 'o1')['shop_id']) == ('pdd', 's1')
        assert (tx.get('orders', 'o2')['platform'], tx.get('orders', 'o2')['shop_id']) == ('pdd', None)
        # Order watermark snapshots are never rewritten by the migration.
        assert tx.get('orders', 'o1')['watermark'] == 'Magnux'
