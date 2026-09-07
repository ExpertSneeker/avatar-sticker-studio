import asyncio
from concurrent.futures import ThreadPoolExecutor
from backend.tests.test_worker import context
from backend.tests.test_library import stickers
from backend.tests.test_api import upload
from backend.tests.test_credits import member


def create_template(client, code, sid):
    return client.post('/api/templates', json={'code':code,'name':'模板 '+code,'category':'general','sticker_ids':[sid]})


def test_delete_sticker_lists_all_referencing_templates_including_inactive(context):
    app,admin,_,_=context
    s=stickers(admin,['DELETE-S']).json()[0]
    a=create_template(admin,'A',s['id']).json()
    b=create_template(admin,'B',s['id']).json()
    admin.patch('/api/templates/'+b['id'],json={'active':False})
    response=admin.delete('/api/stickers/'+s['id'])
    assert response.status_code==409,response.text
    refs=response.json()['detail']['templates']
    assert {(t['code'],t['name'],t['active']) for t in refs}=={('A','模板 A',True),('B','模板 B',False)}
    assert admin.delete('/api/templates/'+a['id']).status_code==200
    assert admin.delete('/api/stickers/'+s['id']).json()['detail']['templates'][0]['id']==b['id']
    assert admin.delete('/api/templates/'+b['id']).status_code==200
    assert admin.delete('/api/stickers/'+s['id']).status_code==200
    assert admin.get('/api/stickers').json()==[]
    assert admin.get('/api/templates').json()==[]
    assert admin.delete('/api/stickers/'+s['id']).status_code==200
    # Deleted codes can be reused, while historic identities remain separate.
    assert stickers(admin,['DELETE-S']).status_code==200


def test_delete_permissions_and_history_survive(context):
    app,admin,_,provider=context
    staff,account=member(admin,app)
    s=stickers(admin,['HISTORY']).json()[0]
    t=create_template(admin,'HISTORY',s['id']).json()
    o=admin.post('/api/orders',json={'upload_id':upload(admin)['id'],'name':'history','template_ids':[t['id']],'client_token':'history'}).json()
    assert staff.delete('/api/templates/'+t['id']).status_code==403
    assert staff.delete('/api/stickers/'+s['id']).status_code==403
    admin.patch('/api/admin/users/'+account['id']+'/library-permission',json={'can_edit_library':True})
    assert staff.delete('/api/templates/'+t['id']).status_code==200
    assert len(admin.get('/api/stickers').json())==1
    assert staff.delete('/api/stickers/'+s['id']).status_code==200
    assert admin.get(s['image']['url']).status_code==200
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    result=admin.get('/api/orders/'+o['id']).json()
    assert result['status']=='completed' and result['total']==1
    assert len(provider.calls)==1 and result['items'][0]['template_url']==s['image']['url']
    with app.state.db.transaction() as tx:
        assert tx.get('template_revisions',t['id']+':1')['images'][0]['id']==s['image']['id']
        assert tx.get('sticker_revisions',s['id']+':1')['image']==s['image']
        assert tx.get('orders',o['id'])['export_entries'][0]['code']=='HISTORY'
    assert admin.post('/api/orders',json={'upload_id':upload(admin)['id'],'name':'gone','sticker_ids':[s['id']],'client_token':'gone'}).status_code==422


def test_template_creation_cannot_race_sticker_deletion(context):
    app,admin,_,_=context
    for n in range(5):
        s=stickers(admin,[f'RACE-{n}']).json()[0]
        with ThreadPoolExecutor(2) as pool:
            creating=pool.submit(create_template,admin,f'RACE-{n}',s['id'])
            deleting=pool.submit(admin.delete,'/api/stickers/'+s['id'])
            statuses=(creating.result().status_code,deleting.result().status_code)
        assert statuses in ((200,409),(422,200)),statuses
