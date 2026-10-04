from backend.tests.test_worker import context
from backend.tests.helpers import order, customer_action, run_all, submit_and_publish, stored_order


def test_cleanup_preserves_customer_history_assets_and_templates(context):
    app,client,clock,_=context
    first,_=order(client,name='旧订单');run_all(app);submit_and_publish(app,client,first)
    assert customer_action(client,first,'repack',print_settings={'long_edge_mm':50}).status_code==200
    app.state.worker.publish(first['id'])
    clock.value+=86400*40
    client.post('/api/auth/login',json={'username':'admin','password':'safe-password-123'})
    second,_=order(client,name='新订单',template_ids=[client.get('/api/templates').json()[0]['id']])
    assert client.get('/api/admin/storage').json()['total_bytes']>0
    templates=client.get('/api/templates').json()
    with app.state.db.transaction(readonly=True) as tx:
        records={kind:tx.all(kind) for kind in ('orders','items','assets','generations')}
    request={'before':'2099-01-01T00:00:00Z'}
    plan=client.post('/api/admin/cleanup/preview',json=request).json()
    assert plan['order_count']==plan['file_count']==0
    response=client.post('/api/admin/cleanup',json={**request,'preview_token':plan['preview_token'],'confirmed':True})
    assert response.status_code==200 and response.json()['pending_files']==0
    for o in (first,second):assert client.get('/api/customer-orders/'+o['id']).status_code==200
    assert client.get('/api/templates').json()==templates
    with app.state.db.transaction(readonly=True) as tx:
        assert {kind:tx.all(kind) for kind in records}==records
        assert all((app.state.db.root/'assets'/a['file']).exists() for a in tx.all('assets'))


def test_cleanup_requires_admin_confirmation_and_protects_reserved(context):
    app,client,_,_=context;value,_=order(client)
    request={'before':'2099-01-01T00:00:00Z'}
    assert app.state.worker.claim()
    plan=client.post('/api/admin/cleanup/preview',json=request).json()
    assert plan['order_count']==0 and plan['blocked_count']==1
    assert client.post('/api/admin/cleanup',json={**request,'preview_token':plan['preview_token'],'confirmed':False}).status_code==422
    assert client.post('/api/admin/cleanup',json={**request,'preview_token':'0'*64,'confirmed':True}).status_code==409
    assert client.get('/api/customer-orders/'+value['id']).status_code==200
    invite=client.post('/api/admin/invites').json()['code'];client.post('/api/auth/logout')
    client.post('/api/auth/register',json={'username':'member','password':'member-password','display_name':'成员','invite':invite})
    assert client.get('/api/admin/storage').status_code==403
    assert client.post('/api/admin/cleanup/preview',json=request).status_code==403


def test_failed_file_removal_is_durable_and_retryable(context,monkeypatch):
    from pathlib import Path
    from backend.app.maintenance import stage_cleanup
    from backend.tests.helpers import upload
    app,client,_,_=context;value=upload(client)
    with app.state.db.transaction() as tx:
        asset=tx.get('assets',value['url'].rsplit('/',1)[-1])
        stage_cleanup(tx,{'assets':[asset]},['assets/'+asset['file']])
    target=app.state.db.root/'assets'/asset['file'];native=Path.unlink
    def blocked(path,*args,**kwargs):
        if path==target:raise PermissionError('test permission denied')
        return native(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',blocked)
    assert client.post('/api/admin/cleanup/retry').json()['pending_files']==1 and target.exists()
    assert client.get(asset['url']).status_code==404
    monkeypatch.setattr(Path,'unlink',native)
    assert client.post('/api/admin/cleanup/retry').json()['pending_files']==0 and not target.exists()
