import json
from backend.tests.test_worker import context
from backend.tests.test_api import png
from backend.tests.test_credits import member


def stickers(client, codes):
    return client.post('/api/stickers', data={'codes':json.dumps(codes),'name':'贴纸','category':'general'}, files=[('files',(f'{code}.png',png(),'image/png')) for code in codes])


def test_library_permissions_shared_revisions_and_availability(context):
    app,admin,_,_=context
    staff,account=member(admin,app)
    assert staff.get('/api/auth/me').json()['can_edit_library'] is False
    assert stickers(staff,['NO']).status_code==403
    response=admin.patch('/api/admin/users/'+account['id']+'/library-permission',json={'can_edit_library':True})
    assert response.status_code==200,response.text
    batch=stickers(staff,['ONE','TWO']);assert batch.status_code==200,batch.text
    one,two=batch.json()
    body={'code':'SET','name':'套装','category':'general','sticker_ids':[two['id'],one['id']]}
    response=staff.post('/api/templates',json=body);assert response.status_code==200,response.text
    template=response.json();assert template['available'] and template['images'][0]['sticker_id']==two['id']
    edited=staff.put('/api/stickers/'+two['id'],data={'code':'TWO-NEW'},files={'file':('new.png',png((20,50,60,255)),'image/png')})
    assert edited.status_code==200,edited.text
    assert edited.json()['revision']==2
    hydrated=staff.get('/api/templates').json()[0]
    assert hydrated['images'][0]['code']=='TWO-NEW'
    with app.state.db.transaction() as tx:
        assert tx.get('sticker_revisions',two['id']+':1')['image']['id']==two['image']['id']
        assert tx.get('template_revisions',template['id']+':1')['images'][0]['id']==two['image']['id']
    assert staff.patch('/api/stickers/'+two['id'],json={'active':False}).status_code==410
    assert staff.get('/api/templates').json()[0]['available']
    admin.patch('/api/admin/users/'+account['id']+'/library-permission',json={'can_edit_library':False})
    assert len(staff.get('/api/stickers').json())==2
    assert staff.put('/api/stickers/'+one['id'],data={'name':'bad'}).status_code==403
    assert staff.get(one['image']['url']).status_code==200


def test_library_validation_is_atomic(context):
    app,admin,_,_=context
    assert stickers(admin,['A','a']).status_code==409
    assert admin.get('/api/stickers').json()==[]
    one=stickers(admin,['ONE']).json()[0]
    assert stickers(admin,['one']).status_code==409
    body={'code':'SET','name':'set','category':'general','sticker_ids':[one['id'],one['id']]}
    assert admin.post('/api/templates',json=body).status_code==422
    assert admin.post('/api/templates',data={'code':'OLD'},files={'files':('a.png',png(),'image/png')}).status_code==422


def test_malformed_uploads_and_reserved_code_leave_no_assets(context):
    app,admin,_,_=context
    for data,files,status in [
        ({'codes':'{}'},[('files',('ok.png',png(),'image/png'))],422),
        ({'codes':'["A","B"]'},[('files',('ok.png',png(),'image/png')),('files',('bad.png',b'broken','image/png'))],400),
        ({'codes':'["拼版"]'},[('files',('ok.png',png(),'image/png'))],422),
    ]:
        response=admin.post('/api/stickers',data=data,files=files)
        assert response.status_code==status,response.text
        with app.state.db.transaction() as tx:
            assert not tx.all('assets') and not tx.all('stickers')
    _,account=member(admin,app)
    assert admin.patch('/api/admin/users/'+account['id']+'/library-permission',json={'can_edit_library':'true'}).status_code==422


def test_admin_permission_cannot_be_revoked_and_empty_metadata_is_rejected(context):
    _,admin,_,_=context
    actor=admin.get('/api/auth/me').json()
    response=admin.patch('/api/admin/users/'+actor['id']+'/library-permission',json={'can_edit_library':False})
    assert response.status_code==200 and response.json()['can_edit_library'] is True
    sticker=stickers(admin,['A']).json()[0]
    assert admin.put('/api/stickers/'+sticker['id'],data={'name':'  '}).status_code==422
    assert admin.get('/api/stickers').json()[0]['revision']==1


def test_batch_transaction_failure_removes_new_files(context,monkeypatch):
    import pytest
    from backend.app import library
    app,admin,_,_=context
    original=library.snapshot
    count=0
    def failing_snapshot(tx,kind,value):
        nonlocal count
        count+=1
        if count==2:
            raise RuntimeError('simulated transaction failure')
        return original(tx,kind,value)
    monkeypatch.setattr(library,'snapshot',failing_snapshot)
    with pytest.raises(RuntimeError,match='simulated transaction failure'):
        stickers(admin,['A','B'])
    with app.state.db.transaction() as tx:
        assert not tx.all('stickers') and not tx.all('sticker_revisions') and not tx.all('assets')
    assert not list((app.state.db.root/'assets').glob('*.png'))


def test_existing_templates_get_1024_revisions_and_history_is_kept(tmp_path):
    from PIL import Image
    from backend.app.db import Database
    from backend.app.storage import save_asset
    from backend.tests.test_api import png
    db = Database(tmp_path)
    with db.transaction() as tx:
        old = save_asset(db, tx, png(size=(1254, 1254)), None, 'template', organization_id='org')
        done = save_asset(db, tx, png(size=(1024, 1024)), None, 'template', organization_id='org')
        for id, asset in (('big', old), ('ok', done)):
            tx.put('stickers', {'id': id, 'organization_id': 'org', 'code': id, 'name': id, 'category': 'general', 'active': True, 'revision': 3, 'image': {'id': asset['id'], 'url': asset['url']}})
        tx.delete('migrations', 'template-1024-v1')
    Database(tmp_path)
    Database(tmp_path)  # idempotent: a second start adds no revision
    with db.transaction() as tx:
        big, ok = tx.get('stickers', 'big'), tx.get('stickers', 'ok')
        assert big['revision'] == 4 and big['image']['id'] != old['id'] and ok['revision'] == 3
        assert tx.get('sticker_revisions', 'big:4')['image'] == big['image']
        new = tx.get('assets', big['image']['id'])
        assert new['kind'] == 'template' and new['organization_id'] == 'org' and new['scope'] == 'public'
        assert tx.get('assets', old['id']) and (db.root / 'assets' / old['file']).exists()
        assert tx.get('migrations', 'template-1024-v1')['resized'] == [{'sticker_id': 'big', 'from': old['id'], 'to': new['id']}]
    assert Image.open(db.root / 'assets' / new['file']).size == (1024, 1024)
