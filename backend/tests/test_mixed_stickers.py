import asyncio
import io
from PIL import Image
from backend.tests.test_worker import context
from backend.tests.test_api import png, upload
from backend.tests.helpers import member, create_customer_order, generate_customer_order, customer_action, order_items, stored_order, run_all, submit_and_publish


def sticker(client, code):
    result = client.post('/api/stickers', data={'codes': __import__('json').dumps([code]), 'category':'general'}, files=[('files',(code+'.png',png(),'image/png'))])
    assert result.status_code == 200, result.text
    return result.json()[0]



def test_mixed_generation_once_exports_every_occurrence(context):
    app,admin,_,provider=context
    a,b=sticker(admin,'A1-01'),sticker(admin,'A1-02')
    t=admin.post('/api/templates',json={'code':'A','name':'A','category':'general','sticker_ids':[a['id'],b['id']]}).json()
    staff,_=member(admin,app)
    o,_=create_customer_order(staff,'Mixed',3)
    o=generate_customer_order(staff,o,template_ids=[t['id']],sticker_ids=[a['id']])
    assert len(o['slots'])==3 and len(order_items(app,o))==2
    assert [s['sticker_code'] for s in o['slots']]==['A1-01','A1-02','A1-01']
    run_all(app);before=staff.get('/api/customer-orders/'+o['id']).json()
    assert len(provider.calls)==2
    assert before['slots'][0]['selected_version_id']==before['slots'][2]['selected_version_id']
    assert customer_action(staff,o,'slots/'+before['slots'][0]['id']+'/rerun').status_code==200
    run_all(app);changed=staff.get('/api/customer-orders/'+o['id']).json()
    assert len(provider.calls)==3 and changed['slots'][2]==before['slots'][2]
    first=changed['slots'][0]
    assert customer_action(staff,o,'slots/'+first['id']+'/select',version_id=first['pending_version_id']).status_code==200
    result=submit_and_publish(app,staff,o)
    manifest=staff.get('/api/customer-orders/'+o['id']+'/manifest').json()
    assert all(f['kind']=='print' for f in manifest['files'])
    assert Image.open(io.BytesIO(staff.get('/api/assets/'+stored_order(app,o)['overview_id']).content)).size==(1024,256)
    saved=stored_order(app,o)
    assert len(saved['final_entries'])==3 and saved['final_entries'][0]['asset_id']!=saved['final_entries'][2]['asset_id']


def test_sticker_only_empty_unavailable_and_snapshot(context):
    app,admin,_,_=context;s=sticker(admin,'ONE')
    o,_=create_customer_order(admin,'one',1)
    o=generate_customer_order(admin,o,sticker_ids=[s['id']])
    assert len(o['slots'])==len(order_items(app,o))==1
    empty,_=create_customer_order(admin,'empty',1)
    body={'avatars':[{'upload_id':upload(admin)['id'],'sticker_ids':[]}]}
    assert customer_action(admin,empty,'generate',**body).status_code==422
    assert admin.put('/api/stickers/'+s['id'],data={'code':'NEW','name':'New','category':'general'}).status_code==200
    assert admin.get('/api/customer-orders/'+o['id']).json()['slots'][0]['sticker_code']=='ONE'
    assert admin.delete('/api/stickers/'+s['id']).status_code==200
    assert customer_action(admin,empty,'generate',avatars=[{'upload_id':upload(admin)['id'],'sticker_ids':[s['id']]}]).status_code==422
    assert order_items(app,o)[0]['template_id']==s['image']['id']


def test_twelve_plus_one_overlapping_templates_and_occurrence_cap(context):
    app,admin,_,provider=context
    sources=admin.post('/api/stickers',files=[('files',(f'A1-{i:02}.png',png(),'image/png')) for i in range(1,13)]).json()
    ids=[s['id'] for s in sources]
    def group(code,members):
        response=admin.post('/api/templates',json={'code':code,'name':code,'category':'general','sticker_ids':members})
        assert response.status_code==200,response.text
        return response.json()
    a=group('A',ids);b=group('B',ids[:2])
    first,_=create_customer_order(admin,'13',13)
    first=generate_customer_order(admin,first,template_ids=[a['id']],sticker_ids=[ids[0]])
    assert len(first['slots'])==13 and len(order_items(app,first))==12
    run_all(app);submit_and_publish(app,admin,first)
    assert len(provider.calls)==12 and len(stored_order(app,first)['final_entries'])==13
    second,_=create_customer_order(admin,'15',15)
    second=generate_customer_order(admin,second,template_ids=[a['id'],b['id']],sticker_ids=[ids[0]])
    assert len(second['slots'])==15 and len(order_items(app,second))==12
    many=[group(f'G{i}',ids)['id'] for i in range(30)]
    limit,_=create_customer_order(admin,'limit',360)
    upload_id=upload(admin)['id']
    assert customer_action(admin,limit,'generate',avatars=[{'upload_id':upload_id,'template_ids':many,'sticker_ids':[ids[0]]}]).status_code==422
    assert order_items(app,limit)==[]
    limit=generate_customer_order(admin,limit,template_ids=many,upload_id=upload_id)
    assert len(limit['slots'])==360 and len(order_items(app,limit))==12


def test_template_snapshot_uses_current_sticker_image(context):
    app,admin,_,_=context;s=sticker(admin,'CURRENT')
    t=admin.post('/api/templates',json={'code':'CURRENT','name':'Current','category':'general','sticker_ids':[s['id']]}).json()
    changed=admin.put('/api/stickers/'+s['id'],data={'code':'LATEST'},files={'file':('replacement.png',png((0,100,0,200)),'image/png')}).json()
    o,_=create_customer_order(admin,'snapshot',1)
    o=generate_customer_order(admin,o,template_ids=[t['id']])
    assert order_items(app,o)[0]['template_id']==changed['image']['id']
    assert o['slots'][0]['sticker_code']=='LATEST'
    with app.state.db.transaction(readonly=True) as tx:
        assert tx.get('template_revisions',t['id']+':1')['images'][0]['id']==s['image']['id']
