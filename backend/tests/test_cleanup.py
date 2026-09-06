import asyncio
from backend.tests.test_worker import context
from backend.tests.test_api import order


def test_cleanup_preview_delete_and_disk_usage_preserve_templates_and_other_orders(context):
    app, client, clock, _ = context
    first, _ = order(client, name='旧订单')
    for _ in range(12):
        asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    # Repacking creates obsolete print/overview assets that must also be removed.
    client.post('/api/orders/'+first['id']+'/repack', json={'print_settings':{'long_edge_mm':50}})
    clock.value += 86400 * 40
    client.post('/api/auth/login',json={'username':'admin','password':'safe-password-123'})
    second, _ = order(client, name='新订单', template_ids=[client.get('/api/templates').json()[0]['id']])
    cutoff='1970-01-20T00:00:00Z'
    before_templates=client.get('/api/templates').json()
    assert client.get('/api/admin/storage').json()['total_bytes'] > 0
    plan=client.post('/api/admin/cleanup/preview',json={'before':cutoff})
    assert plan.status_code == 200, plan.text
    plan=plan.json()
    assert plan['order_count'] == 1
    assert plan['file_count'] > 26
    assert client.get('/api/orders/'+first['id']).status_code == 200
    result=client.post('/api/admin/cleanup',json={'before':cutoff,'preview_token':plan['preview_token'],'confirmed':True})
    assert result.status_code == 200, result.text
    assert result.json()['pending_files'] == 0
    assert client.get('/api/orders/'+first['id']).status_code == 404
    assert client.get('/api/orders/'+second['id']).status_code == 200
    assert client.get('/api/templates').json() == before_templates
    with app.state.db.transaction() as tx:
        assert not any(i['order_id']==first['id'] for i in tx.all('items'))
        assert not any(a.get('order_id')==first['id'] for a in tx.all('assets'))
        assets=tx.all('assets')
    assert len(list((app.state.db.root/'assets').glob('*.png'))) == len(assets)
    assert client.get(second['avatar_url']).status_code == 200


def test_cleanup_requires_admin_confirmation_and_fresh_preview_and_skips_reserved(context):
    app, client, clock, _ = context
    item_order, _=order(client)
    request={'before':'2026-01-01T00:00:00Z'}
    plan=client.post('/api/admin/cleanup/preview',json=request)
    assert plan.status_code == 200
    claimed=app.state.worker.claim()
    assert claimed
    assert client.post('/api/admin/cleanup',json={**request,'preview_token':plan.json()['preview_token'],'confirmed':True}).status_code == 409
    preview=client.post('/api/admin/cleanup/preview',json=request).json()
    assert preview['order_count'] == 0 and preview['blocked_count'] == 1
    assert client.post('/api/admin/cleanup',json={**request,'preview_token':preview['preview_token'],'confirmed':False}).status_code == 422
    assert client.get('/api/orders/'+item_order['id']).status_code == 200
    invite=client.post('/api/admin/invites').json()['code']
    client.post('/api/auth/logout')
    client.post('/api/auth/register',json={'username':'member','password':'member-password','display_name':'成员','invite':invite})
    assert client.get('/api/admin/storage').status_code == 403
    assert client.post('/api/admin/cleanup/preview',json=request).status_code == 403


def test_failed_file_removal_is_durable_and_retryable(context, monkeypatch):
    from pathlib import Path
    app, client, _, _ = context
    value, _ = order(client)
    request={'before':'2026-01-01T00:00:00Z'}
    with app.state.db.transaction() as tx:
        avatar=tx.get('assets',tx.get('orders',value['id'])['avatar_id'])
    target=app.state.db.root/'assets'/avatar['file']
    native=Path.unlink
    def blocked(path,*args,**kwargs):
        if path == target: raise PermissionError('test permission denied')
        return native(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',blocked)
    plan=client.post('/api/admin/cleanup/preview',json=request).json()
    result=client.post('/api/admin/cleanup',json={**request,'preview_token':plan['preview_token'],'confirmed':True})
    assert result.status_code == 200
    assert result.json()['pending_files'] == 1 and target.exists()
    assert client.get('/api/orders/'+value['id']).status_code == 404
    monkeypatch.setattr(Path,'unlink',native)
    assert client.post('/api/admin/cleanup/retry').json()['pending_files'] == 0
    assert not target.exists()
    assert client.get('/api/templates').json()
