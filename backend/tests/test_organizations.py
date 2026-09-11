import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.db import Database
from backend.tests.test_api import png, upload, template


@pytest.fixture
def orgs(tmp_path):
    app = create_app(tmp_path, start_worker=False)
    with TestClient(app) as root, TestClient(app) as one, TestClient(app) as two:
        root.post('/api/auth/setup', json={'username':'root','password':'safe-password-123','display_name':'平台'})
        identities=[]
        for client, name in ((one,'one'),(two,'two')):
            response=root.post('/api/admin/organizations',json={'name':name,'admin_username':name,'admin_display_name':name})
            assert response.status_code == 200, response.text
            body=response.json(); identities.append(body)
            assert client.post('/api/auth/login',json={'username':name,'password':body['temporary_password']}).status_code==200
        yield app,root,one,two,identities


def test_bootstrap_and_org_admin_permissions(orgs):
    app,root,one,two,identities=orgs
    assert root.get('/api/auth/me').json()['role']=='superadmin'
    me=one.get('/api/auth/me').json()
    assert me['role']=='org_admin' and me['organization_name']=='one'
    assert 'credits' not in me
    for endpoint in ('settings','statistics','storage','organizations'):
        assert one.get('/api/admin/'+endpoint).status_code==403
    target=two.get('/api/auth/me').json()['id']
    for suffix in ('concurrency','deletion','credits'):
        assert one.get('/api/admin/users/'+target+'/'+suffix).status_code==404
    assert one.post('/api/admin/users/'+target+'/password').status_code==404
    assert one.patch('/api/admin/users/'+target,json={'active':False}).status_code==404
    assert one.patch('/api/admin/users/'+target+'/library-permission',json={'can_edit_library':True}).status_code==404
    assert {u['organization_id'] for u in one.get('/api/admin/users').json()}=={me['organization_id']}
    member=one.post('/api/admin/users',json={'username':'member','display_name':'成员'}).json()['user']
    assert member['organization_id']==me['organization_id']
    assert root.patch('/api/admin/organizations/'+identities[0]['organization']['id'],json={'active':False}).status_code==200
    assert one.get('/api/auth/me').status_code==401


def test_catalog_upload_cache_and_legacy_order_isolation(orgs):
    app,root,one,two,_=orgs
    first=template(one,'SAME'); second=template(two,'SAME')
    assert [t['id'] for t in one.get('/api/templates').json()]==[first['id']]
    sticker=first['sticker_ids'][0]
    assert two.delete('/api/stickers/'+sticker).status_code==404
    assert two.put('/api/templates/'+first['id'],json={'code':'BAD','name':'bad','sticker_ids':second['sticker_ids']}).status_code==404
    assert two.post('/api/templates',json={'code':'FOREIGN','name':'bad','sticker_ids':[sticker]}).status_code==422
    avatar=upload(one)
    etag=one.get(avatar['url']+'/preview').headers['etag']
    assert two.get(avatar['url']).status_code==404
    assert two.get(avatar['url']+'/preview',headers={'If-None-Match':etag}).status_code==404
    assert two.get('/api/uploads/'+avatar['id']).status_code==404
    payload={'name':'old','upload_id':upload(two)['id'],'template_ids':[first['id']],'client_token':'x'}
    assert two.post('/api/orders',json=payload).status_code in (404,422)
    payload.update(template_ids=[second['id']])
    created=two.post('/api/orders',json=payload)
    assert created.status_code==200,created.text
    assert one.get('/api/orders/'+created.json()['id']).status_code==404
    owner_id=one.get('/api/auth/me').json()['id']
    with app.state.db.transaction() as tx:
        assert all(g['status']=='exempt' for g in tx.all('generations'))
        tx.put('orders',{'id':'new','owner':owner_id,'organization_id':first['organization_id'],'workflow_version':3})
    assert all(o['id']!='new' for o in one.get('/api/orders').json())


def test_same_org_staff_shares_uploads_and_categories_are_isolated(orgs):
    app,root,one,two,_=orgs
    cat=one.post('/api/library/categories',json={'name':'custom'}).json()
    assert cat['id'] not in {c['id'] for c in two.get('/api/library/categories').json()}
    assert two.patch('/api/library/categories/'+cat['id'],json={'name':'stolen'}).status_code==404
    avatar=upload(one)
    invite=one.post('/api/admin/invites').json()['code']
    with TestClient(app) as staff:
        response=staff.post('/api/auth/register',json={'invite':invite,'username':'staff','password':'safe-password-123','display_name':'staff'})
        assert response.status_code==200,response.text
        assert response.json()['organization_id']==one.get('/api/auth/me').json()['organization_id']
        assert staff.get(avatar['url']).status_code==200
        assert staff.get('/api/uploads/'+avatar['id']).status_code==200


def test_migration_retains_unknown_credits_and_organization_history(tmp_path):
    db=Database(tmp_path)
    with db.transaction() as tx:
        tx.delete('migrations','organizations-v1')
        tx.put('users',{'id':'u','username':'magnus','role':'admin','credits':{'available':0,'frozen':2,'spent':0,'version':0}})
        for id,status in (('done','completed'),('unknown','unknown')):
            tx.put('items',{'id':id,'owner':'u','order_id':id,'status':status,'generation_id':id})
            tx.put('generations',{'id':id,'owner':'u','order_id':id,'item_id':id,'status':'reserved'})
    db=Database(tmp_path)
    with db.transaction() as tx:
        user=tx.get('users','u')
        assert user['role']=='org_admin' and user['organization_id']
        assert tx.get('generations','done')['status']=='released'
        assert tx.get('generations','unknown')['status']=='reserved'
        assert user['credits']['frozen']==1


def test_cleanup_preserves_customer_history_and_account(orgs):
    from backend.app.maintenance import cleanup_plan, account_deletion_plan
    from datetime import datetime, timezone
    from fastapi import HTTPException
    app,root,one,two,_=orgs
    member=one.post('/api/admin/users',json={'username':'history','display_name':'history'}).json()['user']
    with app.state.db.transaction() as tx:
        tx.put('orders',{'id':'customer','workflow_version':3,'owner':member['id'],'created_at':'2020-01-01T00:00:00+00:00','state':'cancelled','avatars':[{'id':'a','asset_id':'source'}],'slots':[{'id':'s','versions':[{'id':'v','result_id':'original'}]}]})
        tx.put('assets',{'id':'original','kind':'result','owner':member['id'],'file':'original.png','order_id':'customer'})
        plan,records,paths=cleanup_plan(app.state.db,tx,datetime.now(timezone.utc))
        assert plan['order_count']==0
        assert not records['assets'] and not paths
        with pytest.raises(HTTPException) as error:
            account_deletion_plan(tx,member['id'])
        assert error.value.status_code==409


def test_superadmin_can_reset_organization_admin(orgs):
    app,root,one,two,identities=orgs
    id=identities[0]['admin']['id']
    response=root.post('/api/admin/users/'+id+'/password')
    assert response.status_code==200,response.text
    assert one.get('/api/auth/me').status_code==401
    assert one.post('/api/auth/login',json={'username':'one','password':response.json()['temporary_password']}).status_code==200


def test_superadmin_cli_has_no_default_password_or_default_organization(tmp_path):
    import subprocess, sys
    response=subprocess.run([sys.executable,'-m','backend.app.bootstrap','--data-dir',str(tmp_path),'--username','platform','--display-name','Platform','--generate-password'],text=True,capture_output=True)
    assert response.returncode==0,response.stderr
    import json
    created=json.loads(response.stdout)
    assert len(created['temporary_password'])>=24
    with Database(tmp_path).transaction() as tx:
        user=next(u for u in tx.all('users') if u['username']=='platform')
        assert user['role']=='superadmin' and user['organization_id'] is None
        assert created['temporary_password'] not in user['password']


def test_migration_keeps_custom_category_names_and_source_bytes(tmp_path):
    from backend.app.storage import save_asset
    db=Database(tmp_path)
    with db.transaction() as tx:
        tx.delete('migrations','organizations-v1')
        for org in tx.all('organizations'): tx.delete('organizations',org['id'])
        tx.put('library_categories',{'id':'boy','name':'男生专用'})
        asset=save_asset(db,tx,png(),'legacy','avatar')
        original=(db.root/'assets'/asset['file']).read_bytes()
    Database(tmp_path)
    with db.transaction() as tx:
        assert tx.get('library_categories','boy')['name']=='男生专用'
        assert (db.root/'assets'/asset['file']).read_bytes()==original


def test_migration_keeps_unmatched_legacy_holds_for_audit(tmp_path):
    db=Database(tmp_path)
    with db.transaction() as tx:
        tx.delete('migrations','organizations-v1')
        tx.put('users',{'id':'u','username':'staff','role':'staff','credits':{'available':0,'frozen':0,'spent':0,'version':0}})
        tx.put('items',{'id':'finished','owner':'u','order_id':'old','status':'completed'})
        tx.put('generations',{'id':'unmatched','owner':'u','item_id':'finished','order_id':'old','status':'reserved'})
    Database(tmp_path)
    with db.transaction() as tx:
        assert tx.get('generations','unmatched')['status']=='reserved'
        assert tx.get('users','u')['credits']['frozen']==0
