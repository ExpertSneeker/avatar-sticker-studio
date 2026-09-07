from backend.tests.test_worker import context
from backend.tests.test_library import stickers
from backend.tests.test_credits import member


def test_editable_categories_preserve_ids_and_protect_references(context):
    app, admin, _, _ = context
    staff, account = member(admin, app)
    assert len(admin.get('/api/library/categories').json()) == 4
    assert staff.post('/api/library/categories', json={'name':'节日'}).status_code == 403
    created = admin.post('/api/library/categories', json={'name':'节日'})
    assert created.status_code == 200, created.text
    cat = created.json()
    assert admin.post('/api/library/categories', json={'name':'节日'}).status_code == 409
    s = stickers(admin, ['CAT']).json()[0]
    assert admin.put('/api/stickers/'+s['id'], data={'category':cat['id']}).status_code == 200
    t = admin.post('/api/templates', json={'code':'CAT','name':'节日套装','category':cat['id'],'sticker_ids':[s['id']]}).json()
    assert admin.patch('/api/library/categories/'+cat['id'], json={'name':'节日主题'}).status_code == 200
    blocked = admin.delete('/api/library/categories/'+cat['id'])
    assert blocked.status_code == 409
    assert {r['kind'] for r in blocked.json()['detail']['resources']} == {'stickers','templates'}
    admin.delete('/api/templates/'+t['id'])
    admin.delete('/api/stickers/'+s['id'])
    assert admin.delete('/api/library/categories/'+cat['id']).status_code == 200
    assert admin.put('/api/templates/'+t['id'], json={'code':'CAT','name':'x','category':cat['id'],'sticker_ids':[s['id']]}).status_code != 200
    assert admin.delete('/api/library/categories/general').status_code == 409


def test_batch_edit_atomic_permission_and_historical_snapshots(context):
    app, admin, _, _ = context
    staff, account = member(admin, app)
    a,b = stickers(admin, ['BATCH-A','BATCH-B']).json()
    body={'ids':[a['id'],b['id']], 'action':'update','category':'animal','active':False}
    assert staff.post('/api/stickers/batch',json=body).status_code == 403
    assert admin.post('/api/stickers/batch',json={**body,'ids':[a['id'],'missing']}).status_code == 404
    assert admin.get('/api/stickers').json()[0]['revision']==1
    result=admin.post('/api/stickers/batch',json=body)
    assert result.status_code==200,result.text
    assert all(s['category']=='animal' and not s['active'] and s['revision']==2 for s in admin.get('/api/stickers').json())
    with app.state.db.transaction() as tx:
        assert tx.get('sticker_revisions',a['id']+':1')['active']
        assert tx.get('sticker_revisions',a['id']+':1')['category']=='general'
    assert admin.post('/api/stickers/batch',json={'ids':[a['id']], 'action':'update','category':'missing'}).status_code==422
    assert admin.post('/api/stickers/batch',json={'ids':[a['id']], 'action':'update'}).status_code==422


def test_batch_delete_blocks_entire_selection_and_lists_templates(context):
    _, admin, _, _ = context
    a,b = stickers(admin, ['DEL-A','DEL-B']).json()
    t=admin.post('/api/templates',json={'code':'REF','name':'引用套装','sticker_ids':[b['id']]}).json()
    body={'ids':[a['id'],b['id']], 'action':'delete'}
    result=admin.post('/api/stickers/batch',json=body)
    assert result.status_code==409,result.text
    assert result.json()['detail']['references'][0]['sticker']['code']=='DEL-B'
    assert result.json()['detail']['references'][0]['templates'][0]['id']==t['id']
    assert len(admin.get('/api/stickers').json())==2
    admin.delete('/api/templates/'+t['id'])
    assert admin.post('/api/stickers/batch',json=body).status_code==200
    assert admin.get('/api/stickers').json()==[]
    assert admin.get(a['image']['url']).status_code==200


def test_category_migration_is_idempotent_and_revocation_is_immediate(context):
    from backend.app.db import Database
    app,admin,_,_=context
    staff,account=member(admin,app)
    admin.patch('/api/admin/users/'+account['id']+'/library-permission',json={'can_edit_library':True})
    c=staff.post('/api/library/categories',json={'name':'自定义'}).json()
    assert 'id' in c
    assert staff.patch('/api/library/categories/boy',json={'name':'男生'}).status_code==200
    assert staff.delete('/api/library/categories/girl').status_code==200
    Database(app.state.db.root)
    cats=admin.get('/api/library/categories').json()
    assert any(x['id']=='boy' and x['name']=='男生' for x in cats)
    assert not any(x['id']=='girl' for x in cats)
    assert c in cats
    admin.patch('/api/admin/users/'+account['id']+'/library-permission',json={'can_edit_library':False})
    assert staff.patch('/api/library/categories/'+c['id'],json={'name':'bad'}).status_code==403
    assert staff.delete('/api/library/categories/'+c['id']).status_code==403
