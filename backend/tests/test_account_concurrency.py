import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from backend.tests.test_worker import context,Worker
from backend.tests.test_api import order,template
from backend.tests.test_credits import member,fund


def change(admin,user,value,expected=2):
    return admin.patch('/api/admin/users/'+user['id']+'/concurrency',json={'generation_concurrency':value,'expected_limit':expected})


def test_limits_are_admin_only_validated_and_visible_to_owner(context):
    app,admin,_,_=context;staff,user=member(admin,app)
    assert staff.get('/api/auth/me').json()['generation_concurrency']==2
    assert change(staff,user,3).status_code==403
    assert staff.patch('/api/account',json={'generation_concurrency':3}).status_code==422
    for value in (0,41,1.5,True,'3'):
        assert change(admin,user,value).status_code==422
    assert change(admin,user,3).status_code==200
    assert staff.get('/api/auth/me').json()['generation_concurrency']==3
    assert change(admin,user,4).status_code==409
    assert admin.get('/api/admin/users/'+user['id']+'/concurrency').json()['generation_concurrency']==3
    assert staff.get('/api/admin/users/'+user['id']+'/concurrency').status_code==403
    own=admin.get('/api/auth/me').json()
    assert change(admin,own,4).status_code==200
    # Historical accounts without the field have the same stable default after restart.
    with app.state.db.transaction() as tx:
        target=tx.get('users',user['id']);target.pop('generation_concurrency');tx.put('users',target)
    assert staff.get('/api/auth/me').json()['generation_concurrency']==2
    assert change(admin,{'id':'missing'},2).status_code==404


def test_cross_worker_admission_obeys_both_limits_and_skips_capped_owner(context):
    app,admin,clock,provider=context
    alice,a=member(admin,app,'alice');bob,b=member(admin,app,'bobby')
    fund(admin,a);fund(admin,b);t=template(admin)
    order(alice,template_ids=[t['id']]);order(bob,template_ids=[t['id']])
    assert change(admin,a,1).status_code==200
    assert change(admin,b,3).status_code==200
    admin.patch('/api/admin/settings',json={'max_inflight':3})
    workers=[Worker(app.state.db,provider=provider,clock=clock) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims=[i for i in pool.map(lambda w:w.claim(),workers) if i]
    assert len(claims)==3
    counts=Counter(i['owner'] for i in claims)
    assert counts[a['id']]==1 and counts[b['id']]==2
    assert app.state.worker.claim() is None


def test_lower_limit_preserves_inflight_recovery_unknown_and_postprocessing(context):
    app,admin,clock,provider=context;own=admin.get('/api/auth/me').json()
    admin.patch('/api/admin/settings',json={'max_inflight':8})
    order(admin);w=app.state.worker
    first,second=w.claim(),w.claim();assert first and second
    assert change(admin,own,1).status_code==200
    assert w.claim() is None
    with app.state.db.transaction() as tx:
        i=tx.get('items',first['id']);i.update(status='queued',fal_request_id='existing-paid-request',next_at=0);tx.put('items',i)
    recovered=Worker(app.state.db,provider=provider,clock=clock).claim()
    assert recovered['id']==first['id'] and recovered['attempt']==1
    with app.state.db.transaction() as tx:
        i=tx.get('items',first['id']);i.update(status='unknown');tx.put('items',i)
        i=tx.get('items',second['id']);i.update(status='queued',remote_reserved=False,processing_stage='postprocess',next_at=0);tx.put('items',i)
    assert w.claim()['id']==second['id']
    assert w.claim() is None
    # Only after the reserved unknown request is resolved may the next generation start.
    with app.state.db.transaction() as tx:
        i=tx.get('items',first['id']);i.update(status='failed',remote_reserved=False);tx.put('items',i)
    assert w.claim()


def test_rerun_and_multiple_orders_share_owner_limit(context):
    app,admin,_,_=context;own=admin.get('/api/auth/me').json()
    admin.patch('/api/admin/settings',json={'max_inflight':8})
    assert change(admin,own,1).status_code==200
    first,body=order(admin);order(admin,template_ids=body['template_ids'],name='another')
    w=app.state.worker;i=w.claim();asyncio.run(w.execute(i))
    assert admin.post(f"/api/orders/{first['id']}/items/{i['id']}/rerun",json={'client_token':'limited-rerun'}).status_code==200
    assert w.claim()['id']==i['id']
    assert w.claim() is None
