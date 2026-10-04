import asyncio
from backend.tests.test_worker import context
from backend.tests.helpers import member, order, customer_action, order_items, slot_for


def test_reset_password_revokes_old_sessions(context):
    app,admin,_,_=context;staff,user=member(admin,app)
    response=admin.post('/api/admin/users/'+user['id']+'/password')
    assert response.status_code==200
    assert staff.get('/api/auth/me').status_code==401
    assert staff.post('/api/auth/login',json={'username':user['username'],'password':response.json()['temporary_password']}).status_code==200


def test_stale_run_never_enters_provider(context):
    app,admin,_,provider=context;order(admin)
    old=app.state.worker.claim()
    with app.state.db.transaction() as tx:
        current=tx.get('items',old['id']);current['run_id']='newer-claim';tx.put('items',current)
    asyncio.run(app.state.worker.execute(old))
    assert provider.calls==[]


def test_rerun_replay_after_completion_creates_no_duplicate_work(context):
    app,admin,_,provider=context;o,_=order(admin);w=app.state.worker
    first=w.claim();asyncio.run(w.execute(first));slot=slot_for(app,o,first)
    current=admin.get('/api/customer-orders/'+o['id']).json()
    path='/api/customer-orders/'+o['id']+'/slots/'+slot['id']+'/rerun'
    body={'client_token':'retry-same-operation','expected_version':current['version']}
    assert admin.post(path,json=body).status_code==200
    # Complete every current request, then replay the original operation unchanged.
    while (item:=w.claim()) is not None:asyncio.run(w.execute(item))
    count=len(provider.calls);items=order_items(app,o)
    assert admin.post(path,json=body).status_code==200
    assert len(provider.calls)==count and order_items(app,o)==items


def test_removed_order_and_credit_routes_return_404(context):
    _,admin,_,_=context
    user=admin.get('/api/auth/me').json()
    for method,path in [('get','/api/orders'),('post','/api/orders'),('get','/api/orders/missing'),('post','/api/orders/missing/repack'),('get','/api/orders/missing/manifest'),('get','/api/orders/missing/download.zip'),('get','/api/credits'),('get','/api/admin/users/'+user['id']+'/credits'),('post','/api/admin/users/'+user['id']+'/credits'),('post','/api/admin/generations/missing/settle')]:
        assert getattr(admin,method)(path).status_code==404,(method,path)


def test_concurrent_customer_orders_and_generation_need_no_balance(context):
    from concurrent.futures import ThreadPoolExecutor
    from backend.tests.helpers import template, upload, create_customer_order, generate_customer_order
    app,admin,_,_=context;staff,user=member(admin,app)
    t=template(admin);avatar=upload(staff)
    first,_=create_customer_order(staff,'first',12)
    second,_=create_customer_order(staff,'second',12)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda o:generate_customer_order(staff,o,template_ids=[t['id']],upload_id=avatar['id']),(first,second)))
    assert len({o['id'] for o in results})==2
    with app.state.db.transaction(readonly=True) as tx:
        assert len(tx.all('items'))==len(tx.all('generations'))==24
        assert 'credits' not in tx.get('users',user['id'])
        assert not tx.all('credit_ledger') and not tx.all('credit_operations')


def test_stale_checkpoint_cannot_reopen_manually_resolved_request(context):
    from backend.app.providers import ProviderFailure
    app,admin,_,_=context;o,_=order(admin);w=app.state.worker
    item=w.claim();w.fail(item,ProviderFailure('ambiguous','unknown'))
    slot=slot_for(app,o,item)
    assert customer_action(admin,o,'slots/'+slot['id']+'/resolve',confirmed_ended=True).status_code==200
    before=order_items(app,o)
    w.checkpoint(item,fal_request_id='late-response',status='queued')
    assert order_items(app,o)==before
