import asyncio
from backend.tests.test_worker import context
from backend.tests.test_api import template,upload,png
from backend.tests.test_credits import member,fund
from backend.tests.test_personal_templates import create


def preview(admin,user):
    response=admin.get('/api/admin/users/'+user['id']+'/deletion')
    assert response.status_code==200,response.text
    return response.json()


def remove(admin,user,plan):
    return admin.request('DELETE','/api/admin/users/'+user['id'],json={'username':user['username'],'preview_token':plan['preview_token'],'confirmed':True})


def test_delete_member_removes_private_versions_orders_uploads_and_caches(context):
    app,admin,_,_=context
    public=template(admin)
    staff,user=member(admin,app,'delete_member');fund(admin,user,24)
    private=create(staff,'DELETE-PRIVATE').json()
    old_url=private['images'][0]['url']
    assert staff.get(old_url+'/preview').status_code==200
    revised=staff.put('/api/templates/'+private['id'],data={'code':'DELETE-PRIVATE','name':'Private secret','category':'animal'},files=[('files',(f'{i}.png',png(),'image/png')) for i in range(12)])
    assert revised.status_code==200
    def submit(token):
        return staff.post('/api/orders',json={'upload_id':upload(staff)['id'],'name':'Private order secret','template_ids':[private['id']],'print_settings':{},'client_token':token}).json()
    first=submit('first')
    for _ in range(12):asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    second=submit('second')
    item=staff.get('/api/orders/'+first['id']).json()['items'][0]
    assert staff.get(item['result_url']+'/preview').status_code==200
    partial=staff.post('/api/uploads/init',json={'filename':'unfinished.png','size':10,'sha256':'0'*64}).json()
    assert staff.put('/api/uploads/'+partial['id'],content=b'part',headers={'Upload-Offset':'0'}).status_code==200
    bob,b=member(admin,app,'kept_member');kept=create(bob,'KEEP-PRIVATE').json()
    with app.state.db.transaction() as tx:
        assets=[a for a in tx.all('assets') if a.get('owner')==user['id']]
    plan=preview(admin,user)
    assert plan['order_count']==2 and plan['template_count']==1 and plan['revision_count']==2
    assert plan['can_delete'] and plan['frozen_credits']==12
    response=remove(admin,user,plan);assert response.status_code==200,response.text
    assert response.json()['pending_files']==0
    assert staff.get('/api/auth/me').status_code==401
    assert admin.get('/api/orders/'+first['id']).status_code==404
    assert admin.get(old_url+'/preview',headers={'If-None-Match':'anything'}).status_code==404
    assert admin.get(public['images'][0]['url']).status_code==200
    assert bob.get(kept['images'][0]['url']).status_code==200
    root=app.state.db.root
    assert all(not(root/'assets'/a['file']).exists() and not(root/'preview-cache'/a['id']).exists() for a in assets)
    assert not(root/(partial['id']+'.upload')).exists()
    with app.state.db.transaction() as tx:
        assert tx.get('users',user['id']) is None
        for kind in ('orders','items','uploads','assets','templates','template_revisions','generations'):
            assert not any(r.get('owner')==user['id'] for r in tx.all(kind)),kind
        ledger=[r for r in tx.all('credit_ledger') if r['owner']==user['id']]
        assert sum(r['event']=='charge' for r in ledger)==12
        assert sum(r['event']=='release' for r in ledger)==12
        assert 'Private' not in str(ledger)


def test_account_deletion_requires_admin_confirmation_and_fresh_preview(context):
    app,admin,_,_=context;staff,user=member(admin,app)
    plan=preview(admin,user)
    assert staff.get('/api/admin/users/'+user['id']+'/deletion').status_code==403
    assert remove(staff,user,plan).status_code==403
    assert admin.request('DELETE','/api/admin/users/'+user['id'],json={'username':'wrong','preview_token':plan['preview_token'],'confirmed':True}).status_code==409
    create(staff,'AFTER-PREVIEW')
    assert remove(admin,user,plan).status_code==409
    assert staff.get('/api/auth/me').status_code==200
    own=admin.get('/api/auth/me').json()
    assert admin.get('/api/admin/users/'+own['id']+'/deletion').status_code==403
    assert remove(admin,own,plan).status_code==403


def test_account_deletion_refuses_active_and_unknown_provider_work(context):
    app,admin,_,_=context;staff,user=member(admin,app);fund(admin,user)
    t=template(admin)
    o=staff.post('/api/orders',json={'upload_id':upload(staff)['id'],'name':'busy','template_ids':[t['id']],'print_settings':{},'client_token':'busy'}).json()
    claim=app.state.worker.claim()
    plan=preview(admin,user);assert not plan['can_delete'] and plan['blocked_count']==1
    assert remove(admin,user,plan).status_code==409
    with app.state.db.transaction() as tx:
        item=tx.get('items',claim['id']);item.update(status='unknown',remote_reserved=False);tx.put('items',item)
    plan=preview(admin,user);assert not plan['can_delete']
    assert remove(admin,user,plan).status_code==409
    assert staff.get('/api/auth/me').status_code==200


def test_failed_disk_cleanup_is_durable_and_does_not_restore_account(context,monkeypatch):
    from pathlib import Path
    from backend.app.maintenance import drain_cleanup
    app,admin,_,_=context;staff,user=member(admin,app)
    private=create(staff,'RETRY-DELETE').json()
    staff.get(private['images'][0]['url']+'/preview')
    with app.state.db.transaction() as tx:
        asset=tx.get('assets',private['images'][0]['id'])
    path=app.state.db.root/'assets'/asset['file']
    original=Path.unlink
    def fail_one(self,*args,**kwargs):
        if self==path:raise OSError('temporary disk failure')
        return original(self,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'unlink',fail_one)
        response=remove(admin,user,preview(admin,user))
        assert response.status_code==200 and response.json()['pending_files']==1
    assert path.exists() and staff.get('/api/auth/me').status_code==401
    assert admin.get(asset['url']).status_code==404
    assert drain_cleanup(app.state.db)==0
    assert not path.exists()


def test_worker_claim_after_preview_prevents_deletion(context):
    app,admin,_,_=context;staff,user=member(admin,app);fund(admin,user)
    t=template(admin)
    staff.post('/api/orders',json={'upload_id':upload(staff)['id'],'name':'race','template_ids':[t['id']],'print_settings':{},'client_token':'race'})
    plan=preview(admin,user);assert plan['can_delete']
    assert app.state.worker.claim()
    assert remove(admin,user,plan).status_code==409
    assert staff.get('/api/auth/me').status_code==200
    assert staff.get('/api/credits').json()['wallet']['frozen']==12
