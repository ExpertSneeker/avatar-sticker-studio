import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_api import upload, template, order, png


def member(client, app, name='member'):
    response=client.post('/api/admin/users',json={'username':name,'display_name':name})
    assert response.status_code==200,response.text
    account=response.json()
    other=TestClient(app)
    assert other.post('/api/auth/login',json={'username':name,'password':account['temporary_password']}).status_code==200
    return other,account['user']


def fund(client, user, amount=12, token='fund'):
    balance=client.get('/api/admin/users/'+user['id']+'/credits').json()['wallet']
    return client.post('/api/admin/users/'+user['id']+'/credits',json={'operation':'add','amount':amount,'reason':'测试分配','client_token':token+'-'+user['id'],'expected_version':balance['version']})


def seed_legacy_reservations(app, owner):
    """Replay a pre-removal database, never a new credit reservation."""
    with app.state.db.transaction() as tx:
        generations=[g for g in tx.all('generations') if g['owner']==owner]
        user=tx.get('users',owner)
        user['credits']={'available':0,'frozen':len(generations),'spent':0,'version':0}
        tx.put('users',user)
        for generation in generations:
            generation['status']='reserved';tx.put('generations',generation)


def test_credit_free_generation_rerun_cleanup_and_audit(context):
    app,admin,clock,_=context
    staff,user=member(admin,app)
    t=template(admin)
    data={'upload_id':upload(staff)['id'],'name':'积分订单','template_ids':[t['id']],'print_settings':{},'client_token':'credit-order'}
    result=staff.post('/api/orders',json=data);assert result.status_code==200,result.text
    value=result.json()
    assert staff.post('/api/orders',json=data).json()['id']==value['id']
    with app.state.db.transaction() as tx:
        assert len(tx.all('generations'))==12
        assert all(g['status']=='exempt' for g in tx.all('generations'))
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    item=staff.get('/api/orders/'+value['id']).json()['items'][0]
    assert staff.post(f"/api/orders/{value['id']}/items/{item['id']}/rerun",json={'client_token':'test-rerun'}).status_code==200
    req={'before':'2099-01-01T00:00:00Z'}
    plan=admin.post('/api/admin/cleanup/preview',json=req).json()
    assert admin.post('/api/admin/cleanup',json={**req,'preview_token':plan['preview_token'],'confirmed':True}).status_code==200
    state=staff.get('/api/credits').json()
    assert state['wallet']['available']==state['wallet']['frozen']==state['wallet']['spent']==0
    assert state['entries']==[]


def test_credit_adjustments_are_retired_and_concurrent_orders_need_no_balance(context):
    app,admin,_,_=context;staff,user=member(admin,app)
    body={'operation':'add','amount':12,'reason':'分配','client_token':'same','expected_version':0}
    url='/api/admin/users/'+user['id']+'/credits'
    assert admin.post(url,json=body).status_code==409
    assert staff.post(url,json=body).status_code==403
    t=template(admin);u=upload(staff)
    bodies=[{'upload_id':u['id'],'name':f'并发{i}','template_ids':[t['id']],'print_settings':{},'client_token':f'concurrent{i}'} for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda body:staff.post('/api/orders',json=body),bodies))
    assert sorted(r.status_code for r in responses)==[200,200]
    assert len({r.json()['id'] for r in responses})==2
    wallet=staff.get('/api/credits').json()['wallet'];assert (wallet['available'],wallet['frozen'])==(0,0)


def test_unknown_manual_resolution_preserves_hold_until_admin_settlement(context):
    from backend.app.providers import ProviderFailure
    app,admin,_,_=context;staff,user=member(admin,app);fund(admin,user)
    t=template(admin);o,_=order(staff,template_ids=[t['id']])
    seed_legacy_reservations(app,user['id'])
    item=app.state.worker.claim()
    app.state.worker.fail(item,ProviderFailure('unknown test','unknown'))
    detail=staff.get('/api/credits').json();gid=detail['pending'][0]['id']
    assert detail['wallet']['frozen']==12
    assert staff.post(f"/api/orders/{o['id']}/items/{item['id']}/resolve",json={'confirmed_ended':True}).status_code==200
    assert staff.get('/api/credits').json()['wallet']['frozen']==12
    body={'outcome':'release','reason':'平台确认没有成图','client_token':'settle'}
    assert staff.post('/api/admin/generations/'+gid+'/settle',json=body).status_code==403
    response=admin.post('/api/admin/generations/'+gid+'/settle',json=body)
    assert response.status_code==200,response.text
    assert response.json()['available']==1 and response.json()['frozen']==11
    assert admin.post('/api/admin/generations/'+gid+'/settle',json=body).json()['available']==1


def test_reset_password_revokes_old_sessions_and_admin_is_exempt(context):
    app,admin,_,_=context;staff,user=member(admin,app)
    assert admin.get('/api/credits').json()['wallet']['exempt']
    o,_=order(admin)
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    assert admin.get('/api/credits').json()['wallet']['spent']==0
    response=admin.post('/api/admin/users/'+user['id']+'/password')
    assert response.status_code==200
    assert staff.get('/api/auth/me').status_code==401
    assert staff.post('/api/auth/login',json={'username':user['username'],'password':response.json()['temporary_password']}).status_code==200


def test_stale_worker_checkpoint_cannot_reopen_refunded_generation(context):
    from backend.app.providers import ProviderFailure
    app,admin,clock,_=context;staff,user=member(admin,app);fund(admin,user)
    o,_=order(staff,template_ids=[template(admin)['id']]);worker=app.state.worker
    seed_legacy_reservations(app,user['id'])
    item=worker.claim();worker.fail(item,ProviderFailure('lost','unknown'))
    gid=staff.get('/api/credits').json()['pending'][0]['id']
    response=admin.post('/api/admin/generations/'+gid+'/settle',json={'outcome':'release','reason':'未生成','client_token':'settle'})
    assert response.status_code==200
    worker.checkpoint(item,fal_request_id='late-response',status='queued')
    with app.state.db.transaction() as tx:
        assert tx.get('items',item['id'])['status']=='failed'
        assert not tx.get('items',item['id']).get('fal_request_id')


def test_postprocess_failure_charged_once_and_generation_failure_released(context):
    from backend.app.providers import ProviderFailure
    app,admin,_,provider=context;staff,user=member(admin,app);fund(admin,user)
    o,_=order(staff,template_ids=[template(admin)['id']]);worker=app.state.worker
    seed_legacy_reservations(app,user['id'])
    first=worker.claim();provider.error=ProviderFailure('rejected','failed')
    asyncio.run(worker.execute(first))
    assert staff.get('/api/credits').json()['wallet']['available']==1
    provider.error=None
    async def opaque(**kw):return png((255,0,0,255),(1024,1024))
    # Explicitly opaque complete canvas forces the existing missing-cutout failure.
    from PIL import Image
    import io
    async def opaque(**kw):
        out=io.BytesIO();Image.new('RGBA',(1024,1024),'red').save(out,'PNG');return out.getvalue()
    provider.generate=opaque
    second=worker.claim();asyncio.run(worker.execute(second))
    state=staff.get('/api/credits').json()['wallet'];assert state['spent']==1 and state['frozen']==10
    assert staff.post(f"/api/orders/{o['id']}/items/{second['id']}/reprocess").status_code==200
    asyncio.run(worker.execute(worker.claim()))
    assert staff.get('/api/credits').json()['wallet']==state


def test_existing_data_migration_keeps_templates_accounts_and_legacy_jobs(context):
    from backend.app.db import Database
    app,admin,clock,_=context;o,_=order(admin)
    staff,user=member(admin,app)
    with app.state.db.transaction() as tx:
        tx.delete('migrations','personal-credits-v1')
        for kind in ('templates','template_revisions'):
            for row in tx.all(kind):
                row.pop('scope',None);row.pop('owner',None);tx.put(kind,row)
        for item in tx.all('items'):
            item['owner']=user['id'];item.pop('generation_id',None);tx.put('items',item)
        order_row=tx.get('orders',o['id']);order_row['owner']=user['id'];tx.put('orders',order_row)
        for gen in tx.all('generations'):tx.delete('generations',gen['id'])
        password=tx.get('users',user['id'])['password']
    Database(app.state.db.root)
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    assert staff.get('/api/credits').json()['wallet']['spent']==0
    with app.state.db.transaction() as tx:
        assert tx.get('users',user['id'])['password']==password
        assert all(t['scope']=='public' for t in tx.all('templates'))
        assert all(i['billing_legacy'] for i in tx.all('items'))
    assert fund(admin,user,1).status_code==409
    first=staff.get('/api/orders/'+o['id']).json()['items'][0]
    assert staff.post(f"/api/orders/{o['id']}/items/{first['id']}/rerun",json={'client_token':'test-rerun'}).status_code==200
    assert staff.get('/api/credits').json()['wallet']['frozen']==0


def test_rerun_replay_after_completion_does_not_generate_or_charge_again(context):
    app,admin,_,provider=context;staff,user=member(admin,app);fund(admin,user,13)
    o,_=order(staff,template_ids=[template(admin)['id']]);worker=app.state.worker
    item=worker.claim();asyncio.run(worker.execute(item))
    url=f"/api/orders/{o['id']}/items/{item['id']}/rerun"
    body={'client_token':'retry-same-operation'}
    assert staff.post(url,json=body).status_code==200
    asyncio.run(worker.execute(worker.claim()))
    before=staff.get('/api/credits').json()['wallet']
    assert staff.post(url,json=body).status_code==200
    assert staff.get('/api/credits').json()['wallet']==before
    assert staff.get('/api/orders/'+o['id']).json()['items'][0]['status']=='completed'
    assert len(provider.calls)==2


def test_stale_run_never_enters_provider(context):
    app,admin,_,provider=context;order(admin)
    old=app.state.worker.claim()
    with app.state.db.transaction() as tx:
        current=tx.get('items',old['id']);current['run_id']='newer-claim';tx.put('items',current)
    asyncio.run(app.state.worker.execute(old))
    assert provider.calls==[]
