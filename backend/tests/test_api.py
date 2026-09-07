import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app


def png(color=(180, 50, 30, 180), size=(32, 32)):
    image = Image.new('RGBA', size)
    image.paste(color, (4, 4, size[0] - 4, size[1] - 4))
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, start_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        response = client.post('/api/auth/setup', json={'username': 'admin', 'password': 'safe-password-123', 'display_name': '管理员'})
        assert response.status_code == 200, response.text
        yield client


def upload(client, data=None):
    data = data or png()
    result = client.post('/api/uploads/init', json={'filename': '头像.png', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}).json()
    assert client.put('/api/uploads/' + result['id'], content=data, headers={'Upload-Offset': '0'}).status_code == 200
    response = client.post('/api/uploads/' + result['id'] + '/complete')
    assert response.status_code == 200, response.text
    return response.json()


def template(client, code='A01'):
    response = client.post('/api/stickers', data={'category': 'boy'}, files=[('files', (f'{code}-{i+1:02}.png', png((i * 10, 50, 20, 200)), 'image/png')) for i in range(12)])
    assert response.status_code == 200, response.text
    response = client.post('/api/templates', json={'code':code, 'name':'测试套装', 'category':'boy', 'sticker_ids':[s['id'] for s in response.json()]})
    assert response.status_code == 200, response.text
    return response.json()


def order(client, name='小明', template_ids=None):
    body = {'upload_id': upload(client)['id'], 'name': name, 'template_ids': template_ids or [template(client)['id']], 'print_settings': {}, 'client_token': name + '-token'}
    response = client.post('/api/orders', json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def test_setup_invite_and_asset_ownership(client, app):
    assert client.post('/api/auth/setup', json={'username': 'evil', 'password': 'safe-password-123', 'display_name': 'x'}).status_code == 409
    asset = upload(client)
    invite = client.post('/api/admin/invites').json()['code']
    with TestClient(app) as other:
        assert other.post('/api/auth/register', json={'invite': invite, 'username': 'staff', 'password': 'safe-password-123', 'display_name': '员工'}).status_code == 200
        assert other.get(asset['url']).status_code == 404
        assert other.get('/api/admin/settings').status_code == 403
        assert other.post('/api/auth/register', json={'invite': invite, 'username': 'third', 'password': 'safe-password-123', 'display_name': '员工'}).status_code in (400, 409)
    assert client.get(asset['url']).status_code == 200


def test_upload_resume_duplicate_chunk_and_bad_hash(client):
    data = png()
    body = {'filename': 'resume.png', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    u = client.post('/api/uploads/init', json=body).json()['id']
    first = data[:30]
    assert client.put('/api/uploads/' + u, content=first, headers={'Upload-Offset': '0'}).json()['offset'] == 30
    assert client.put('/api/uploads/' + u, content=first, headers={'Upload-Offset': '0'}).json()['offset'] == 30
    assert client.get('/api/uploads/' + u).json()['offset'] == 30
    assert client.put('/api/uploads/' + u, content=b'x', headers={'Upload-Offset': '0'}).status_code == 409
    client.put('/api/uploads/' + u, content=data[30:], headers={'Upload-Offset': '30'})
    assert client.post('/api/uploads/' + u + '/complete').status_code == 200
    body['sha256'] = '0' * 64
    bad = client.post('/api/uploads/init', json=body).json()['id']
    client.put('/api/uploads/' + bad, content=data, headers={'Upload-Offset': '0'})
    assert client.post('/api/uploads/' + bad + '/complete').status_code == 400


def test_template_revision_and_order_idempotency(client):
    t = template(client)
    o, body = order(client, template_ids=[t['id']])
    assert len(client.get('/api/orders/' + o['id']).json()['items']) == 12
    assert client.post('/api/orders', json=body).json()['id'] == o['id']
    body['client_token'] = 'another'
    assert client.post('/api/orders', json=body).json()['id'] != o['id']
    before = client.get('/api/orders/' + o['id']).json()['items'][0]['template_url']
    response = client.put('/api/templates/' + t['id'], json={'code': 'A01', 'name': '调整', 'category': 'girl', 'sticker_ids': list(reversed(t['sticker_ids']))})
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 2
    assert client.get('/api/orders/' + o['id']).json()['items'][0]['template_url'] == before


def test_validation_csrf_and_secret_redaction(client):
    assert client.post('/api/uploads/init', json={'filename': '../escape.png', 'size': 1, 'sha256': '0' * 64}).status_code == 422
    assert client.patch('/api/admin/settings', json={'rpm': 0}).status_code == 422
    assert client.patch('/api/account', json={'watermark': 'x'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.patch('/api/admin/settings', json={'fal_api_key': 'test-secret-not-real'}).status_code == 200
    text = client.get('/api/admin/settings').text
    assert 'test-secret' not in text
    assert '"fal_configured":true' in text


def test_print_options_are_boolean_and_template_replacement_keeps_slot(client):
    response = client.patch('/api/account', json={'print_defaults': {'brightness': True, 'color_balance': True}})
    assert response.status_code == 200, response.text
    assert response.json()['print_defaults']['brightness'] is True
    t = template(client)
    fresh = client.post('/api/stickers',files=[('files',('new.png',png(),'image/png'))]).json()[0]
    members = list(t['sticker_ids']); members[4] = fresh['id']
    result = client.put('/api/templates/' + t['id'], json={'code':t['code'], 'name':t['name'], 'category':t['category'], 'sticker_ids':members})
    assert result.status_code == 200, result.text
    images = result.json()['images']
    keep = [x['id'] for x in t['images']]
    assert images[3]['id'] == t['images'][3]['id']
    assert images[4]['id'] not in keep
    assert images[5]['id'] == t['images'][5]['id']


def json_dumps(value):
    import json
    return json.dumps(value)


def test_upload_hash_failure_can_restart_same_upload(client):
    data = png()
    body = {'filename': 'retry.png', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    id = client.post('/api/uploads/init', json=body).json()['id']
    client.put('/api/uploads/' + id, content=b'x' * len(data), headers={'Upload-Offset': '0'})
    assert client.post('/api/uploads/' + id + '/complete').status_code == 400
    assert client.get('/api/uploads/' + id).json()['offset'] == 0
    assert client.put('/api/uploads/' + id, content=data, headers={'Upload-Offset': '0'}).status_code == 200
    assert client.post('/api/uploads/' + id + '/complete').status_code == 200


def test_dns_rebinding_host_is_rejected(app):
    with TestClient(app, base_url='http://attacker.example') as attacker:
        assert attacker.get('/api/auth/status').status_code == 400
        assert attacker.post('/api/auth/setup', headers={'Origin': 'http://attacker.example'}, json={'username': 'admin', 'password': 'safe-password-123', 'display_name': '管理员'}).status_code == 400


def test_categories_are_canonical_and_whitespace_names_rejected(client):
    assert template(client)['category'] == 'boy'
    assert client.patch('/api/account', json={'display_name': '   '}).status_code == 422


def test_expected_account_header_blocks_cross_tab_cookie_switch_before_mutations(client, app):
    admin_user = client.get('/api/auth/me').json()
    t = template(client)
    raw = png()
    pending = client.post('/api/uploads/init', json={'filename': 'pending.png', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}).json()
    invite = client.post('/api/admin/invites').json()['code']
    with TestClient(app) as other:
        member = other.post('/api/auth/register', json={'invite': invite, 'username': 'member', 'password': 'safe-password-123', 'display_name': '成员'}).json()
        # Browser tabs share cookies: the old admin tab now sends the member session.
        client.cookies = other.cookies
        stale = {'X-Studio-User': admin_user['id']}
        init = client.post('/api/uploads/init', headers=stale, json={'filename': 'blocked.png', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        assert init.status_code == 401
        assert init.json()['detail'] == '登录账号已变化，请重新登录'
        assert client.put('/api/uploads/' + pending['id'], headers={**stale, 'Upload-Offset': '0'}, content=raw).status_code == 401
        assert client.post('/api/orders', headers=stale, json={'upload_id': pending['id'], 'name': '不得创建', 'template_ids': [t['id']], 'print_settings': {}, 'client_token': 'blocked'}).status_code == 401
        assert client.patch('/api/admin/settings', headers=stale, json={'max_inflight': 9}).status_code == 401
        assert client.patch('/api/account', headers=stale, json={'display_name': '不得修改'}).status_code == 401
        assert client.post('/api/auth/logout', headers=stale).status_code == 401
        own = {'X-Studio-User': member['id']}
        assert client.post('/api/uploads/init', headers=own, json={'filename': 'member.png', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}).status_code == 200
        assert client.patch('/api/account', headers=own, json={'display_name': '成员本人'}).status_code == 200
    with app.state.db.transaction() as tx:
        assert tx.get('uploads', pending['id'])['offset'] == 0
        assert not any(u['filename'] == 'blocked.png' for u in tx.all('uploads'))
        assert not tx.all('orders')
        assert tx.get('config', 'settings')['max_inflight'] == 2
        assert tx.get('users', admin_user['id'])['display_name'] == '管理员'


def test_fal_config_migration_preserves_other_data(tmp_path, monkeypatch):
    from backend.app.db import Database
    monkeypatch.setenv('OPENAI_API_KEY','must-not-be-used')
    db=Database(tmp_path)
    with db.transaction() as tx:
        tx.put('config', {'id':'settings','rpm':5,'max_inflight':9,'prompt':'retained prompt','prompt_version':7,'openai_api_key':'must-not-be-used'})
        tx.put('orders', {'id':'retained-order'})
    db=Database(tmp_path)
    with db.transaction() as tx:
        c=tx.get('config','settings')
        assert 'rpm' not in c and 'openai_api_key' not in c
        assert c['max_inflight']==9 and c['prompt_version']==7
        assert not c.get('fal_api_key')
        assert tx.get('orders','retained-order')


def test_same_name_orders_remain_independent_with_distinct_output_folders(client):
    t = template(client)
    body = {'upload_id':upload(client)['id'], 'name':'小明', 'template_ids':[t['id']], 'print_settings':{}, 'client_token':'same-name-1'}
    first = client.post('/api/orders',json=body).json()
    body['client_token']='same-name-2'
    response=client.post('/api/orders',json=body)
    assert response.status_code==200, response.text
    second=response.json()
    assert first['id']!=second['id'] and first['name']==second['name']=='小明'
    assert client.post('/api/orders',json=body).json()['id']==second['id']
    assert client.get('/api/orders/'+first['id']+'/manifest').json()['name']=='小明'
    assert client.get('/api/orders/'+second['id']+'/manifest').json()['name']=='小明 (2)'
    body.update(name='小明 (2)',client_token='literal-folder-name')
    third=client.post('/api/orders',json=body).json()
    assert client.get('/api/orders/'+third['id']+'/manifest').json()['name']=='小明 (2) (2)'
    assert len({i['id'] for o in (first,second,third) for i in o['items']})==36
    from backend.app.storage import save_asset
    import io, zipfile
    db=client.app.state.db
    with db.transaction() as tx:
        for result,color in ((first,(255,0,0,255)),(second,(0,255,0,255))):
            value=tx.get('orders',result['id'])
            asset=save_asset(db,tx,png(color),value['owner'],'print',order_id=value['id'])
            value['artifacts']=[{'id':asset['id'],'path':'小明_A01_1.png'}]
            tx.put('orders',value)
    response=client.get('/api/orders/'+second['id']+'/download.zip')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist()==['小明 (2)/小明_A01_1.png']
        assert archive.read(archive.namelist()[0])==png((0,255,0,255))
