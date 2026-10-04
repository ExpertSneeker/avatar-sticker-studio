import asyncio
from backend.tests.test_worker import context
from backend.tests.test_api import template,upload,png
from backend.tests.helpers import member, order, customer_action, order_items, run_all, stored_order


def preview(admin,user):
    response=admin.get('/api/admin/users/'+user['id']+'/deletion')
    assert response.status_code==200,response.text
    return response.json()


def remove(admin,user,plan):
    return admin.request('DELETE','/api/admin/users/'+user['id'],json={'username':user['username'],'preview_token':plan['preview_token'],'confirmed':True})


def test_delete_member_without_orders_removes_uploads_caches_and_preserves_shared_library(context):
    app,admin,_,_=context;public=template(admin)
    staff,user=member(admin,app,'delete_member')
    assert admin.patch('/api/admin/users/'+user['id']+'/library-permission',json={'can_edit_library':True}).status_code==200
    shared=template(staff,'MEMBER-SHARED');old_url=shared['images'][0]['url']
    assert staff.get(old_url+'/preview').status_code==200
    revised=staff.put('/api/templates/'+shared['id'],json={'code':'MEMBER-SHARED','name':'Shared revised','category':'animal','sticker_ids':list(reversed(shared['sticker_ids']))})
    assert revised.status_code==200
    avatar=upload(staff);assert staff.get(avatar['url']+'/preview').status_code==200
    partial=staff.post('/api/uploads/init',json={'filename':'unfinished.png','size':10,'sha256':'0'*64}).json()
    assert staff.put('/api/uploads/'+partial['id'],content=b'part',headers={'Upload-Offset':'0'}).status_code==200
    bob,_=member(admin,app,'kept_member')
    with app.state.db.transaction(readonly=True) as tx:assets=[a for a in tx.all('assets') if a.get('owner')==user['id']]
    plan=preview(admin,user)
    assert plan['order_count']==plan['template_count']==plan['revision_count']==0 and plan['can_delete']
    assert 'frozen_credits' not in plan
    response=remove(admin,user,plan);assert response.status_code==200,response.text
    assert response.json()['pending_files']==0 and staff.get('/api/auth/me').status_code==401
    assert admin.get(old_url+'/preview',headers={'If-None-Match':'anything'}).status_code==200
    assert any(t['id']==shared['id'] for t in bob.get('/api/templates').json())
    assert admin.get(public['images'][0]['url']).status_code==200
    root_dir=app.state.db.root
    assert all(not(root_dir/'assets'/a['file']).exists() and not(root_dir/'preview-cache'/a['id']).exists() for a in assets)
    assert not(root_dir/(partial['id']+'.upload')).exists()
    with app.state.db.transaction(readonly=True) as tx:
        assert tx.get('users',user['id']) is None
        for kind in ('orders','items','uploads','assets','generations'):
            assert not any(r.get('owner')==user['id'] for r in tx.all(kind)),kind

def test_account_deletion_requires_admin_confirmation_and_fresh_preview(context):
    app,admin,_,_=context;staff,user=member(admin,app)
    plan=preview(admin,user)
    assert staff.get('/api/admin/users/'+user['id']+'/deletion').status_code==403
    assert remove(staff,user,plan).status_code==403
    assert admin.request('DELETE','/api/admin/users/'+user['id'],json={'username':'wrong','preview_token':plan['preview_token'],'confirmed':True}).status_code==409
    upload(staff)
    assert remove(admin,user,plan).status_code==409
    assert staff.get('/api/auth/me').status_code==200
    own=admin.get('/api/auth/me').json()
    assert admin.get('/api/admin/users/'+own['id']+'/deletion').status_code==403
    assert remove(admin,own,plan).status_code==403


def test_account_deletion_refuses_all_customer_history_including_unknown(context):
    app,admin,_,_=context;staff,user=member(admin,app);t=template(admin)
    o,_=order(staff,template_ids=[t['id']]);claim=app.state.worker.claim()
    for status in ('running','unknown','failed','completed'):
        with app.state.db.transaction() as tx:
            item=tx.get('items',claim['id']);item.update(status=status);tx.put('items',item)
        response=admin.get('/api/admin/users/'+user['id']+'/deletion')
        assert response.status_code==409 and '客户订单历史' in response.text
        assert remove(admin,user,{'preview_token':'0'*64}).status_code==409
    assert customer_action(staff,o,'cancel').status_code==200
    assert admin.get('/api/admin/users/'+user['id']+'/deletion').status_code==409
    assert staff.get('/api/auth/me').status_code==200

def test_failed_disk_cleanup_is_durable_and_does_not_restore_account(context,monkeypatch):
    from pathlib import Path
    from backend.app.maintenance import drain_cleanup
    app,admin,_,_=context;staff,user=member(admin,app)
    private=upload(staff)
    staff.get(private['url']+'/preview')
    with app.state.db.transaction() as tx:
        asset=tx.get('assets',private['url'].rsplit('/',1)[-1])
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


def test_order_creation_after_preview_prevents_deletion(context):
    app,admin,_,_=context;staff,user=member(admin,app);t=template(admin)
    plan=preview(admin,user);assert plan['can_delete']
    order(staff,template_ids=[t['id']]);assert app.state.worker.claim()
    assert remove(admin,user,plan).status_code==409
    assert staff.get('/api/auth/me').status_code==200
