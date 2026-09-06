import json
from backend.tests.test_worker import context
from backend.tests.test_api import png, template, upload
from backend.tests.test_credits import member, fund


def create(client, code, scope='personal', category='animal'):
    return client.post('/api/templates',data={'code':code,'name':code,'category':category,'scope':scope},files=[('files',(f'{i}.png',png(),'image/png')) for i in range(12)])


def test_personal_template_permissions_cover_original_cache_and_order(context):
    app,admin,_,_=context
    alice,a=member(admin,app,'alice');bob,b=member(admin,app,'bobby')
    public=template(admin)
    response=create(alice,'ANIMAL');assert response.status_code==200,response.text
    personal=response.json();assert personal['scope']=='personal' and personal['editable']
    assert create(alice,'PUBLIC','public').status_code==403
    assert personal['id'] not in [t['id'] for t in bob.get('/api/templates').json()]
    url=personal['images'][0]['url']
    cached=alice.get(url+'/preview');assert cached.status_code==200
    assert bob.get(url).status_code==404
    assert bob.get(url+'/preview',headers={'If-None-Match':cached.headers['etag']}).status_code==404
    assert admin.get(url).status_code==200
    assert bob.patch('/api/templates/'+personal['id'],json={'active':False}).status_code==404
    assert admin.patch('/api/templates/'+personal['id'],json={'active':False}).status_code==403
    assert bob.put('/api/templates/'+personal['id'],data={'code':'ANIMAL','name':'steal','category':'general','existing_ids':json.dumps([i['id'] for i in personal['images']])}).status_code==404
    assert fund(admin,b,24).status_code==200
    data={'upload_id':upload(bob)['id'],'name':'bad','template_ids':[personal['id']],'print_settings':{},'client_token':'bad'}
    assert bob.post('/api/orders',json=data).status_code==422
    assert bob.get('/api/credits').json()['wallet']['available']==24
    fund(admin,a,24)
    data.update(upload_id=upload(alice)['id'],name='mixed',template_ids=[personal['id'],public['id']],client_token='mixed')
    o=alice.post('/api/orders',json=data);assert o.status_code==200,o.text
    assert len(o.json()['items'])==24
    result=alice.put('/api/templates/'+personal['id'],data={'code':'ANIMAL','name':'general','category':'general','existing_ids':json.dumps([i['id'] for i in reversed(personal['images'])])})
    assert result.status_code==200 and result.json()['category']=='general'
    assert alice.get('/api/orders/'+o.json()['id']).json()['items'][0]['template_url']==personal['images'][0]['url']
    assert alice.patch('/api/templates/'+personal['id'],json={'active':False}).status_code==200
    assert any(t['id']==personal['id'] for t in alice.get('/api/templates').json())
