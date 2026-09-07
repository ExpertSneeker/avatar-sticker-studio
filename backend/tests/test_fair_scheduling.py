from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from backend.tests.test_worker import context,Worker
from backend.tests.test_api import template,order
from backend.tests.test_credits import member,fund
from backend.tests.test_account_concurrency import change


def setup_accounts(context,global_limit=20):
    app,admin,clock,provider=context
    a,au=member(admin,app,'fair_alice');b,bu=member(admin,app,'fair_bob')
    for u in (au,bu):
        fund(admin,u,48)
        assert change(admin,u,20).status_code==200
    admin.patch('/api/admin/settings',json={'max_inflight':global_limit})
    t=template(admin)
    return a,au,b,bu,t


def queue(client,t):
    order(client,template_ids=[t['id']],name='one')
    order(client,template_ids=[t['id']],name='two')


def finish(db,item):
    with db.transaction() as tx:
        current=tx.get('items',item['id']);current.update(status='completed',remote_reserved=False);tx.put('items',current)


def test_twenty_shared_slots_balance_ten_each_across_workers(context):
    app,_,clock,provider=context;a,au,b,bu,t=setup_accounts(context)
    queue(a,t);queue(b,t)
    workers=[Worker(app.state.db,provider=provider,clock=clock) for _ in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims=[i for i in pool.map(lambda w:w.claim(),workers) if i]
    assert Counter(i['owner'] for i in claims)=={au['id']:10,bu['id']:10}


def test_one_slot_rotates_accounts_across_restarts_and_multiple_orders(context):
    app,_,clock,provider=context;a,au,b,bu,t=setup_accounts(context,1)
    queue(a,t);queue(b,t)
    owners=[]
    for _ in range(8):
        claim=Worker(app.state.db,provider=provider,clock=clock).claim()
        owners.append(claim['owner']);finish(app.state.db,claim)
    assert owners==[au['id'],bu['id']]*4


def test_late_account_receives_released_slots_without_cancelling_existing_work(context):
    app,_,_,_=context;a,au,b,bu,t=setup_accounts(context)
    queue(a,t);w=app.state.worker
    claims=[w.claim() for _ in range(20)]
    assert all(i['owner']==au['id'] for i in claims)
    queue(b,t);assert w.claim() is None
    for claim in claims[:10]:
        finish(app.state.db,claim)
        assert w.claim()['owner']==bu['id']
    with app.state.db.transaction() as tx:
        active=[i for i in tx.all('items') if i.get('remote_reserved')]
        assert Counter(i['owner'] for i in active)=={au['id']:10,bu['id']:10}
        assert all(tx.get('items',i['id'])['status']=='running' for i in claims[10:])


def test_unused_share_goes_to_other_account_within_its_limit(context):
    app,admin,_,_=context;a,au,b,bu,t=setup_accounts(context,8)
    assert change(admin,au,2,expected=20).status_code==200
    queue(a,t);queue(b,t)
    claims=[app.state.worker.claim() for _ in range(8)]
    assert Counter(i['owner'] for i in claims)=={au['id']:2,bu['id']:6}
