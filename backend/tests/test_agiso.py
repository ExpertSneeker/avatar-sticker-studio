"""Agiso boundaries use only local HTTP transports and disposable SQLite."""
import asyncio
import hashlib
import json
from urllib.parse import parse_qs, urlsplit
import pytest
import httpx
from backend.tests.test_worker import context

KEY = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='

@pytest.fixture
def configured(context, monkeypatch):
    app, client, clock, _ = context
    for name, value in {'STUDIO_AGISO_APP_ID':'app','STUDIO_AGISO_APP_SECRET':'secret','STUDIO_AGISO_ENCRYPTION_KEY':KEY,'STUDIO_AGISO_PUBLIC_URL':'https://studio.example','STUDIO_AGISO_AFTERSALES_VERIFIED':'1'}.items():
        monkeypatch.setenv(name,value)
    return app,client,clock


def provider(request):
    if request.url.path == '/auth/token':
        return httpx.Response(200,json={'IsSuccess':True,'Data':{'FromPlatform':'PddAlds','ShopId':'999','ShopName':'测试店','Token':'private-token','ExpiresIn':86400}})
    return httpx.Response(200,json={'IsSuccess':True,'Data':True})


def shop(configured, quota=10):
    app,c,clock=configured
    assert c.get('/api/agiso/status').status_code==200
    app.state.agiso_worker.transport=httpx.MockTransport(provider)
    result=c.post('/api/agiso/authorize',json={}); assert result.status_code==200,result.text
    state=parse_qs(urlsplit(result.json()['url'].replace('/#/','/')).query)['state'][0]
    result=c.get('/api/agiso/callback',params={'state':state,'code':'code'},follow_redirects=False)
    assert result.headers['location']=='/?agiso=connected',result.text
    row=c.get('/api/agiso/shops').json()[0]
    rule={'goods_id':'111','sku_id':'222','goods_name':'商品','sku_name':'10张','generation_limit':quota,'final_count':quota,'rerun_limit':2,'enabled':True}
    assert c.put('/api/agiso/shops/'+row['id']+'/rules',json={'rules':[rule]}).status_code==200
    assert c.patch('/api/agiso/shops/'+row['id'],json={'enabled':True}).status_code==200
    return row


def trade(number='ORDER-1',count=1,**kw):
    return {'MallId':'999','Tid':number,'OrderSn':number,'ConfirmTime':'2026-09-14 10:00:00','CreatedTime':'2026-09-14 09:00:00','PayAmount':'10.00','ItemList':[{'goods_id':'111','sku_id':'222','goods_count':count}],**kw}


def push(c,payload,topic='1',signature=True):
    raw=json.dumps(payload,separators=(',',':'),ensure_ascii=False)
    timestamp='1000'
    sign=hashlib.md5(('secretjson'+raw+'timestamp'+timestamp+'secret').encode()).hexdigest() if signature else 'bad'
    return c.post('/api/agiso/webhook',params={'timestamp':timestamp,'sign':sign,'aopic':topic,'fromPlatform':'PddAlds'},data={'json':raw})


def process(app):
    return asyncio.run(app.state.agiso_worker.process_once())


@pytest.mark.parametrize('quota,count',[(10,1),(10,2),(20,1),(20,2)])
def test_exact_quotas_durable_duplicate_and_snapshot(configured,quota,count):
    app,c,clock=configured; s=shop(configured,quota)
    response=push(c,trade(count=count)); assert response.status_code==200 and response.content==b''
    assert c.get('/api/customer-orders').json()==[]
    process(app)
    o=c.get('/api/customer-orders').json()[0]
    assert (o['generation_limit'],o['final_count'],o['rerun_limit'])==(quota*count,quota*count,2)
    assert o['watermark']=='管理员'
    push(c,trade(count=count)); process(app)
    assert len(c.get('/api/customer-orders').json())==1
    process(app)
    row=c.get('/api/agiso/shops/'+s['id']+'/orders').json()[0]
    assert row['message_status']=='sent' and row['guest_url']=='https://studio.example/guest?order_number=ORDER-1'
    c.post('/api/guest/login',json={'order_number':'ORDER-1'})
    assert c.get('/api/agiso/shops/'+s['id']+'/orders').json()[0]['entered_at']==clock()
    assert 'private-token' not in json.dumps(c.get('/api/agiso/shops').json())
    assert b'private-token' not in app.state.db.path.read_bytes()


def test_oauth_state_one_time_and_unconfigured(context,configured):
    app,c,clock=configured; shop(configured)
    result=c.post('/api/agiso/authorize',json={}).json()
    state=parse_qs(urlsplit(result['url'].replace('/#/','/')).query)['state'][0]
    clock.value+=901
    assert c.get('/api/agiso/callback',params={'state':state,'code':'x'},follow_redirects=False).headers['location']=='/?agiso=error'
    assert c.get('/api/agiso/callback',params={'state':'wrong','code':'x'},follow_redirects=False).headers['location']=='/?agiso=error'


@pytest.mark.parametrize('changes',[{'MallId':'other'},{'ItemList':[{'goods_id':'111','sku_id':'wrong','goods_count':1}]},{'ItemList':[{'goods_id':'111','sku_id':'222','goods_count':37}]}])
def test_unrelated_or_invalid_never_opens(configured,changes):
    app,c,_=configured;shop(configured)
    push(c,trade(**changes));process(app);process(app)
    assert c.get('/api/customer-orders').json()==[]


def test_signatures_and_topic_cannot_reinterpret(configured):
    app,c,_=configured;shop(configured)
    assert push(c,trade(),signature=False).status_code==403
    assert push(c,trade(),topic='8').status_code==422
    assert push(c,trade(ItemList=[{'goods_id':'111','sku_id':'222','goods_count':1.2}])).status_code==422
    assert c.post('/api/agiso/webhook',content='x'*262145).status_code==413
    process(app);assert c.get('/api/customer-orders').json()==[]


def test_unknown_send_and_crash_do_not_retry(configured):
    app,c,clock=configured;s=shop(configured)
    push(c,trade());process(app)
    def timeout(request): raise httpx.ReadTimeout('do not expose private-token')
    app.state.agiso_worker.transport=httpx.MockTransport(timeout)
    process(app)
    row=c.get('/api/agiso/shops/'+s['id']+'/orders').json()[0]
    assert row['message_status']=='unknown' and not row['can_retry']
    assert c.post('/api/agiso/shops/'+s['id']+'/orders/'+row['id']+'/retry-message',json={}).status_code==409
    process(app)
    assert 'private-token' not in json.dumps(row)


def refund(number='ORDER-1',rid='R1',op=1200,fee=1000,modified=1000):
    return {'mall_id':'999','tid':number,'refund_id':rid,'bill_type':1,'refund_fee':fee,'modified':modified,'operation':op}


def test_refund_hold_blocks_guest_and_full_success_cancels(configured):
    app,c,_=configured;shop(configured)
    push(c,trade());process(app)
    c.post('/api/guest/login',json={'order_number':'ORDER-1'})
    push(c,refund(),topic='8');process(app)
    g=c.get('/api/guest/order').json();assert g['paused'] and g['hold_reason']
    body={'client_token':'x','expected_version':g['version'],'avatars':[{'upload_id':'x','sticker_ids':['x']}]}
    assert c.post('/api/guest/order/preflight',json=body).status_code==409
    push(c,refund(op=1304,modified=2000),topic='16');process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='cancelled'
    push(c,refund(op=1300,modified=3000),topic='32');process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='cancelled'


def test_refund_before_trade_never_opens_and_manual_collision(configured):
    app,c,_=configured;shop(configured)
    push(c,refund(op=1304),topic='16');process(app)
    push(c,trade());process(app)
    assert c.get('/api/customer-orders').json()==[]
    from backend.tests.test_customer_orders import opened
    opened(c,'MANUAL')
    push(c,trade('MANUAL'));process(app)
    assert len(c.get('/api/customer-orders').json())==1


def test_event_replay_and_rules_snapshot(configured):
    app,c,_=configured;s=shop(configured)
    push(c,trade(ItemList=[{'goods_id':'111','sku_id':'new','goods_count':1}]))
    process(app)
    events=c.get('/api/agiso/shops/'+s['id']+'/events').json();assert events[0]['can_replay']
    rules=c.get('/api/agiso/shops/'+s['id']+'/rules').json();rules[0]['sku_id']='new'
    c.put('/api/agiso/shops/'+s['id']+'/rules',json={'rules':rules})
    assert c.post('/api/agiso/shops/'+s['id']+'/events/'+events[0]['id']+'/replay',json={}).status_code==200
    process(app)
    order=c.get('/api/customer-orders').json()[0]
    rules[0]['generation_limit']=20;rules[0]['final_count']=20
    c.put('/api/agiso/shops/'+s['id']+'/rules',json={'rules':rules})
    assert c.get('/api/customer-orders/'+order['id']).json()['generation_limit']==10


def test_disabled_shop_account_and_organization_block_send(configured):
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    worker=app.state.agiso_worker
    c.patch('/api/agiso/shops/'+s['id'],json={'enabled':False})
    assert worker.claim_message() is None
    c.patch('/api/agiso/shops/'+s['id'],json={'enabled':True})
    with app.state.db.transaction() as tx:
        owner=tx.get('users',s['owner']);owner['active']=False;tx.put('users',owner)
    assert worker.claim_message() is None
    with app.state.db.transaction() as tx:
        owner['active']=True;tx.put('users',owner)
        org=tx.get('organizations',s['organization_id']);org['active']=False;tx.put('organizations',org)
    assert worker.claim_message() is None


def test_claim_is_atomic_and_crash_after_send_never_retries(configured):
    from backend.app.agiso_worker import AgisoWorker
    from concurrent.futures import ThreadPoolExecutor
    app,c,clock=configured;shop(configured)
    push(c,trade());process(app)
    first=app.state.agiso_worker;second=AgisoWorker(app.state.db,clock,httpx.MockTransport(provider))
    with ThreadPoolExecutor(2) as pool:
        claims=list(pool.map(lambda worker:worker.claim_message(),[first,second]))
    assert sum(job is not None for job in claims)==1
    job=next(j for j in claims if j)
    with app.state.db.transaction() as tx:
        row=tx.get('agiso_outbox',job['id']);row['status']='sending';tx.put('agiso_outbox',row)
    clock.value+=61;second.recover()
    with app.state.db.transaction() as tx:
        assert tx.get('agiso_outbox',job['id'])['status']=='unknown'
    assert first.claim_message() is None and second.claim_message() is None


def test_explicit_retry_is_bounded_and_manual_cap(configured):
    app,c,clock=configured;s=shop(configured)
    push(c,trade());process(app)
    app.state.agiso_worker.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'IsSuccess':False,'AllowRetry':True}))
    for _ in range(3):process(app);clock.value+=31
    row=c.get('/api/agiso/shops/'+s['id']+'/orders').json()[0]
    assert row['message_status']=='failed' and row['can_retry']
    for _ in range(2):
        assert c.post('/api/agiso/shops/'+s['id']+'/orders/'+row['id']+'/retry-message',json={}).status_code==200
        process(app);clock.value+=31
    assert c.post('/api/agiso/shops/'+s['id']+'/orders/'+row['id']+'/retry-message',json={}).status_code==409
    with app.state.db.transaction() as tx:assert tx.get('agiso_orders',row['id'])['send_attempts']==5


def test_overlapping_refunds_release_only_own_hold_and_no_manual_resume(configured):
    app,c,_=configured;shop(configured)
    push(c,trade());process(app)
    for rid in ('R1','R2'):push(c,refund(rid=rid),topic='8');process(app)
    push(c,refund(op=1300,modified=2000),topic='32');process(app)
    assert c.get('/api/customer-orders').json()[0]['paused']
    with app.state.db.transaction() as tx:
        order=tx.all('orders')[0];order['paused']=True;tx.put('orders',order)
    push(c,refund(rid='R2',op=1303,modified=2000),topic='32');process(app)
    assert c.get('/api/customer-orders').json()[0]['paused']
    push(c,refund(rid='R2',op=1200,modified=1000),topic='8');process(app)
    with app.state.db.transaction() as tx:assert not tx.all('orders')[0]['integration_holds']


def test_partial_refund_is_manual_and_blocks_notification(configured):
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    push(c,refund(op=1304,fee=500),topic='16');process(app)
    assert c.get('/api/customer-orders').json()[0]['paused']
    row=c.get('/api/agiso/shops/'+s['id']+'/orders').json()[0]
    assert row['open_status']=='manual'
    assert app.state.agiso_worker.claim_message() is None


def test_pending_refund_blocks_claim_and_presend_generation(configured):
    from backend.tests.test_customer_orders import generate
    from backend.tests.test_mixed_stickers import sticker
    app,c,_=configured;shop(configured)
    push(c,trade());process(app)
    order=c.get('/api/customer-orders').json()[0]
    order=generate(c,order,sticker(c,'AG')['id'],count=10)
    item=app.state.worker.claim();assert item
    push(c,refund(),topic='8');process(app)
    asyncio.run(app.state.worker.execute(item))
    assert app.state.worker.provider.calls==[]
    assert app.state.worker.claim() is None


def test_concurrent_confirmation_creates_exactly_one_order(configured):
    from backend.app.agiso_worker import AgisoWorker
    from concurrent.futures import ThreadPoolExecutor
    app,c,clock=configured;shop(configured)
    for amount in ('10.00','11.00'):push(c,trade(PayAmount=amount))
    workers=[app.state.agiso_worker,AgisoWorker(app.state.db,clock)]
    with ThreadPoolExecutor(2) as pool:list(pool.map(lambda worker:worker.process_event(),workers))
    assert len(c.get('/api/customer-orders').json())==1
    with app.state.db.transaction() as tx:assert len(tx.all('agiso_outbox'))==1


def test_invalid_confirmation_time_is_rejected(configured):
    app,c,_=configured;shop(configured)
    assert push(c,trade(ConfirmTime='0')).status_code==422
    assert push(c,trade(ConfirmTime='not confirmed')).status_code==422
    assert c.get('/api/customer-orders').json()==[]


def test_payment_before_group_without_confirmation_time_still_opens(configured):
    app,c,_=configured;shop(configured)
    payload=trade();payload.pop('ConfirmTime')
    assert push(c,payload).status_code==200
    process(app)
    orders=c.get('/api/customer-orders').json()
    assert len(orders)==1 and orders[0]['order_number']=='ORDER-1'


def test_unsupported_push_topic_is_recorded_without_processing(configured):
    app,c,_=configured;s=shop(configured)
    assert push(c,{'MallId':'999','Tid':'ORDER-1','OrderSn':'ORDER-1','Status':'70'},topic='4096').status_code==200
    assert c.get('/api/customer-orders').json()==[]
    events=c.get('/api/agiso/shops/'+s['id']+'/events').json()
    assert len(events)==1 and events[0]['topic']=='4096' and events[0]['status']=='ignored'
    assert not events[0]['can_replay']
    process(app)
    assert c.get('/api/customer-orders').json()==[]


def test_durable_unprocessed_refund_blocks_generation_admission(configured):
    from backend.tests.test_customer_orders import generate
    from backend.tests.test_mixed_stickers import sticker
    app,c,_=configured;shop(configured)
    push(c,trade());process(app)
    order=generate(c,c.get('/api/customer-orders').json()[0],sticker(c,'WAIT')['id'],count=10)
    push(c,refund(),topic='8')
    assert app.state.worker.claim() is None


def test_disabled_owner_blocks_guest_mutations(configured):
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    g=c.post('/api/guest/login',json={'order_number':'ORDER-1'}).json()
    with app.state.db.transaction() as tx:
        owner=tx.get('users',s['owner']);owner['active']=False;tx.put('users',owner)
    response=c.post('/api/guest/order/preflight',json={'client_token':'x','expected_version':g['version'],'avatars':[{'upload_id':'x','sticker_ids':['x']}]})
    assert response.status_code in (401,409)


def test_goods_ids_preserve_precision_and_provider_errors_safe(configured):
    app,c,_=configured;s=shop(configured)
    app.state.agiso_worker.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'IsSuccess':True,'Data':{'total_count':1,'goods_list':[{'goods_id':999999999999999999,'goods_name':'商品','sku_list':[{'sku_id':888888888888888888,'spec':'10张'}]}]}}))
    response=c.get('/api/agiso/shops/'+s['id']+'/goods').json()
    assert response['available'] and response['goods'][0]['skus'][0]['sku_id']=='888888888888888888'
    app.state.agiso_worker.transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'https://evil.example/private-token'}))
    response=c.get('/api/agiso/shops/'+s['id']+'/goods').json()
    assert not response['available'] and 'private-token' not in json.dumps(response)


def test_tenant_scope_and_owner_admin_write_permissions(configured):
    from backend.app.auth import token_hash
    from backend.app.db import uid
    from fastapi.testclient import TestClient
    app,c,clock=configured;s=shop(configured)
    # Use the actual cookie set by auth routes rather than assuming its label.
    cookie_name=next(iter(c.cookies.keys()))
    with app.state.db.transaction() as tx:
        source=tx.get('users',s['owner']);member={**source,'id':uid(),'username':uid(),'role':'user'};tx.put('users',member)
        token=uid();tx.put('sessions',{'id':token_hash(token),'user_id':member['id'],'expires':clock()+10000})
    member_client=TestClient(app);member_client.cookies.set(cookie_name,token)
    assert member_client.get('/api/agiso/shops/'+s['id']+'/rules').status_code==200
    assert member_client.patch('/api/agiso/shops/'+s['id'],json={'enabled':False}).status_code==403
    with app.state.db.transaction() as tx:
        organization={'id':uid(),'name':'other','active':True};tx.put('organizations',organization)
        member['organization_id']=organization['id'];tx.put('users',member)
    assert member_client.get('/api/agiso/shops').json()==[]
    assert member_client.get('/api/agiso/shops/'+s['id']+'/rules').status_code==404


def test_provider_refusal_without_allow_retry_cannot_manual_retry(configured):
    app,c,_=configured;s=shop(configured);push(c,trade());process(app)
    app.state.agiso_worker.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'IsSuccess':False,'AllowRetry':False}))
    process(app)
    row=c.get('/api/agiso/shops/'+s['id']+'/orders').json()[0]
    assert not row['can_retry']
    assert c.post('/api/agiso/shops/'+s['id']+'/orders/'+row['id']+'/retry-message',json={}).status_code==409


def test_expired_authorization_event_resumes_after_reauthorization(configured):
    app,c,clock=configured;s=shop(configured)
    clock.value+=86401
    push(c,trade());process(app)
    assert c.get('/api/customer-orders').json()==[]
    events=c.get('/api/agiso/shops/'+s['id']+'/events').json()
    assert events[0]['status']=='blocked' and events[0]['error']=='authorization_expired'
    shop(configured);process(app)
    assert len(c.get('/api/customer-orders').json())==1


def test_referrer_policy_protects_order_number_and_oauth(context):
    _,c,_,_=context
    assert c.get('/api/agiso/status').headers.get('referrer-policy')=='no-referrer'


def test_oauth_cross_site_return_uses_bound_lax_nonce(configured):
    app,c,_=configured;shop(configured)
    response=c.post('/api/agiso/authorize',json={})
    assert 'samesite=lax' in response.headers['set-cookie'].lower()
    state=parse_qs(urlsplit(response.json()['url'].replace('/#/','/')).query)['state'][0]
    c.cookies.delete('studio_session')
    result=c.get('/api/agiso/callback',params={'state':state,'code':'ok'},follow_redirects=False)
    assert result.headers['location']=='/?agiso=connected'
    assert c.get('/api/agiso/callback',params={'state':state,'code':'ok'},follow_redirects=False).headers['location']=='/?agiso=error'


def test_pending_refund_before_trade_resumes_only_after_all_holds_release(configured):
    app,c,_=configured;shop(configured)
    push(c,refund(),topic='8');process(app)
    push(c,trade());process(app)
    assert c.get('/api/customer-orders').json()==[]
    push(c,refund(op=1300,modified=2000),topic='32');process(app);process(app)
    assert len(c.get('/api/customer-orders').json())==1


def test_oauth_nonce_is_browser_bound_and_terminal_failure_clears_cookie(configured):
    from fastapi.testclient import TestClient
    app,c,_=configured;shop(configured)
    response=c.post('/api/agiso/authorize',json={})
    state=parse_qs(urlsplit(response.json()['url'].replace('/#/','/')).query)['state'][0]
    stranger=TestClient(app)
    result=stranger.get('/api/agiso/callback',params={'state':state,'code':'ok'},follow_redirects=False)
    assert result.headers['location']=='/?agiso=error'
    assert 'Max-Age=0' in result.headers.get('set-cookie','')
    c.post('/api/auth/logout')
    assert c.get('/api/agiso/callback',params={'state':state,'code':'ok'},follow_redirects=False).headers['location']=='/?agiso=error'


def test_signed_order_number_cannot_poison_worker_queue(configured):
    app,c,_=configured;shop(configured)
    assert push(c,trade(OrderSn='bad*number')).status_code==422
    push(c,trade());process(app)
    assert len(c.get('/api/customer-orders').json())==1


def test_disabled_shop_preserves_existing_guest_work_but_blocks_new_activation_and_send(configured):
    from backend.tests.test_customer_orders import generate
    from backend.tests.test_mixed_stickers import sticker
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    order=generate(c,c.get('/api/customer-orders').json()[0],sticker(c,'EXISTING')['id'],count=10)
    c.post('/api/guest/login',json={'order_number':'ORDER-1'})
    c.patch('/api/agiso/shops/'+s['id'],json={'enabled':False})
    item=app.state.worker.claim()
    assert item is not None
    asyncio.run(app.state.worker.execute(item))
    assert len(app.state.worker.provider.calls)==1
    guest=c.get('/api/guest/order').json()
    assert guest['slots'][0]['versions'] and not guest['paused']
    rerun=c.post('/api/guest/order/slots/'+guest['slots'][0]['id']+'/rerun',json={'client_token':'disabled-shop-rerun','expected_version':guest['version']})
    assert rerun.status_code==200,rerun.text
    assert app.state.agiso_worker.claim_message() is None
    push(c,trade('NEW-ORDER'));process(app)
    assert len(c.get('/api/customer-orders').json())==1


def test_disabled_shop_still_applies_verified_refunds_to_existing_order(configured):
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    c.post('/api/guest/login',json={'order_number':'ORDER-1'})
    c.patch('/api/agiso/shops/'+s['id'],json={'enabled':False})
    assert push(c,refund(),topic='8').status_code==200
    process(app)
    order=c.get('/api/customer-orders').json()[0]
    assert order['paused'] and order['hold_reason']
    push(c,refund(op=1304,modified=2000),topic='16');process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='cancelled'
    assert c.get('/api/guest/order').status_code==401
    assert app.state.agiso_worker.claim_message() is None


def test_unverified_refund_on_disabled_shop_remains_record_only(configured,monkeypatch):
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    c.patch('/api/agiso/shops/'+s['id'],json={'enabled':False})
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_VERIFIED','0')
    push(c,refund(op=1304),topic='16');process(app)
    order=c.get('/api/customer-orders').json()[0]
    assert order['state']=='draft' and not order['paused']


def test_refunds_recorded_while_aftersales_disabled_apply_once_enabled(configured,monkeypatch):
    app,c,_=configured;shop(configured)
    push(c,trade());process(app)
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_VERIFIED','0')
    push(c,refund(),topic='8');process(app)
    push(c,refund(op=1304,modified=2000),topic='16');process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='draft'
    monkeypatch.setenv('STUDIO_AGISO_AFTERSALES_VERIFIED','1')
    process(app);process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='cancelled'
    assert c.get('/api/guest/order').status_code==401


def test_previously_switch_disabled_refund_is_recovered_without_reopening_shop(configured):
    app,c,_=configured;s=shop(configured)
    push(c,trade());process(app)
    c.patch('/api/agiso/shops/'+s['id'],json={'enabled':False})
    push(c,refund(op=1304),topic='16')
    with app.state.db.transaction() as tx:
        event=next(e for e in tx.all('agiso_events') if e['topic']=='16')
        event.update(status='disabled',error='shop_disabled');tx.put('agiso_events',event)
    process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='cancelled'


def test_pending_refund_dto_matches_admission_even_with_expired_authorization(configured):
    app,c,clock=configured;shop(configured)
    push(c,trade());process(app)
    c.post('/api/guest/login',json={'order_number':'ORDER-1'})
    clock.value+=86401
    assert not c.get('/api/guest/order').json()['paused']
    push(c,refund(),topic='8')
    guest=c.get('/api/guest/order').json()
    assert guest['paused'] and guest['hold_reason']
    staff=c.get('/api/customer-orders').json()[0]
    assert staff['paused'] and staff['hold_reason']
    process(app)
    assert c.get('/api/guest/order').json()['paused']
    push(c,refund(op=1304,modified=2000),topic='16');process(app)
    assert c.get('/api/customer-orders').json()[0]['state']=='cancelled'

@pytest.mark.parametrize('camel',[False,True])
def test_token_exchange_accepts_documented_and_live_casing(configured,camel):
    from backend.app import agiso_protocol as p
    data={'FromPlatform':'PddAlds','ShopId':'999','ShopName':'测试店','Token':'private-token','ExpiresIn':86400}
    body={'IsSuccess':True,'Data':data}
    if camel:
        body={'isSuccess':True,'data':{k[0].lower()+k[1:]:v for k,v in data.items()}}
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))
    result=asyncio.run(p.exchange('code',p.settings(),transport,1000))
    assert result['shop_id']=='999' and result['expires_at']==87400


def test_token_exchange_rejects_conflicting_aliases(configured):
    from backend.app import agiso_protocol as p
    body={'IsSuccess':False,'isSuccess':True}
    with pytest.raises(p.ProtocolError):
        asyncio.run(p.exchange('code',p.settings(),httpx.MockTransport(lambda r:httpx.Response(200,json=body)),1000))

@pytest.mark.parametrize('camel',[False,True])
@pytest.mark.parametrize('platform',['PddAlds','AldsPdd'])
def test_pdd_user_id_fallback_binds_once(configured,camel,platform):
    app,c,clock=configured
    data={'FromPlatform':platform,'UserId':999,'ShopName':'测试店','Token':'private-token','ExpiresIn':86400}
    if camel:data={k[0].lower()+k[1:]:v for k,v in data.items()}
    app.state.agiso_worker.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'isSuccess':True,'data':data}))
    for _ in range(2):
        state=parse_qs(urlsplit(c.post('/api/agiso/authorize',json={}).json()['url'].replace('/#/','/')).query)['state'][0]
        result=c.get('/api/agiso/callback',params={'state':state,'code':'code'},follow_redirects=False)
        assert result.headers['location']=='/?agiso=connected'
    rows=c.get('/api/agiso/shops').json()
    assert len(rows)==1 and rows[0]['shop_id']=='999' and not rows[0]['enabled']

@pytest.mark.parametrize('extra',[{'ShopId':'888','UserId':'999'},{'UserId':True},{'UserId':'999','FromPlatform':'Open'}])
def test_pdd_identity_rejects_conflicts_and_wrong_platform(configured,extra):
    from backend.app import agiso_protocol as p
    data={'FromPlatform':'PddAlds','ShopName':'测试店','Token':'private-token','ExpiresIn':86400,**extra}
    with pytest.raises((p.ProtocolError,ValueError)):
        asyncio.run(p.exchange('code',p.settings(),httpx.MockTransport(lambda r:httpx.Response(200,json={'IsSuccess':True,'Data':data})),1000))


def test_goods_disabled_permission_has_actionable_safe_message(configured):
    app,c,clock=configured;s=shop(configured)
    app.state.agiso_worker.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'IsSuccess':False,'Error_Code':17,'Error_Msg':'private provider details'}))
    result=c.get('/api/agiso/shops/'+s['id']+'/goods').json()
    assert result['available'] is False and result['goods']==[]
    assert '17' in result['message'] and '权限' in result['message']
    assert 'private provider' not in result['message']
