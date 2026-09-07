import asyncio
import io
from PIL import Image
from backend.tests.test_worker import context
from backend.tests.test_api import png, upload
from backend.tests.test_credits import member, fund


def sticker(client, code):
    result = client.post('/api/stickers', data={'codes': __import__('json').dumps([code]), 'category':'general'}, files=[('files',(code+'.png',png(),'image/png'))])
    assert result.status_code == 200, result.text
    return result.json()[0]


def test_mixed_generation_once_exports_every_occurrence(context):
    app, admin, clock, provider = context
    a, b = sticker(admin, 'A1-01'), sticker(admin, 'A1-02')
    t = admin.post('/api/templates', json={'code':'A','name':'A','category':'general','sticker_ids':[a['id'],b['id']]}).json()
    staff, user = member(admin, app)
    fund(admin,user,3)
    response = staff.post('/api/orders', json={'upload_id':upload(staff)['id'],'name':'Mixed','template_ids':[t['id']],'sticker_ids':[a['id']],'print_settings':{},'client_token':'mixed'})
    assert response.status_code == 200, response.text
    o = response.json()
    assert (o['generation_count'], o['export_count'], len(o['items'])) == (2,3,2)
    assert [e['code'] for e in o['export_entries']] == ['A1-01','A1-02','A1-01']
    assert staff.get('/api/credits').json()['wallet']['frozen'] == 2
    for _ in range(2):
        asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    result=staff.get('/api/orders/'+o['id']).json()
    assert result['status']=='completed', result
    assert len(provider.calls)==2
    assert staff.get('/api/credits').json()['wallet']['spent']==2
    manifest=staff.get('/api/orders/'+o['id']+'/manifest').json()
    files=manifest['files']; single=[f for f in files if f['kind']=='sticker']
    assert [f['path'] for f in single]==['Mixed_A1-01_1.png','Mixed_A1-02_1.png','Mixed_A1-01_2.png']
    assert staff.get(single[0]['url']).content==staff.get(single[2]['url']).content
    assert any(f['path']=='Mixed_拼版_1.png' for f in files)
    overview=next(f for f in files if f['kind']=='overview')
    assert Image.open(io.BytesIO(staff.get(overview['url']).content)).size==(1024,256)
    item=o['items'][0]
    rerun=staff.post('/api/orders/'+o['id']+'/items/'+item['id']+'/rerun',json={'client_token':'redo'})
    assert rerun.status_code==200,rerun.text
    asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    latest=staff.get('/api/orders/'+o['id']).json()
    assert latest['status']=='completed'
    assert len(provider.calls)==3
    assert staff.get('/api/credits').json()['wallet']['spent']==3
    copies=[f for f in latest['artifacts'] if f['kind']=='sticker' and 'A1-01' in f['path']]
    assert len(copies)==2 and copies[0]['id']==copies[1]['id']


def test_sticker_only_empty_unavailable_and_snapshot(context):
    app,admin,clock,provider=context
    s=sticker(admin,'ONE')
    body={'upload_id':upload(admin)['id'],'name':'one','sticker_ids':[s['id']],'client_token':'one'}
    response=admin.post('/api/orders',json=body)
    assert response.status_code==200,response.text
    old=response.json()
    assert old['export_count']==old['total']==1
    assert admin.post('/api/orders',json={**body,'sticker_ids':[],'client_token':'empty'}).status_code==422
    assert admin.put('/api/stickers/'+s['id'],data={'code':'NEW','name':'New','category':'general'}).status_code==200
    assert admin.get('/api/orders/'+old['id']).json()['export_entries'][0]['code']=='ONE'
    assert admin.patch('/api/stickers/'+s['id'],json={'active':False}).status_code==200
    assert admin.post('/api/orders',json={**body,'client_token':'disabled'}).status_code==422
    assert admin.post('/api/orders',json=body).json()['id']==old['id']


def test_twelve_plus_one_and_overlapping_templates(context):
    app,admin,clock,provider=context
    sources=admin.post('/api/stickers', files=[('files',(f'A1-{i:02}.png',png(),'image/png')) for i in range(1,13)]).json()
    ids=[s['id'] for s in sources]
    def group(code,members):
        response=admin.post('/api/templates',json={'code':code,'name':code,'category':'general','sticker_ids':members})
        assert response.status_code==200,response.text
        return response.json()
    a=group('A',ids); b=group('B',ids[:2])
    body={'upload_id':upload(admin)['id'],'name':'验收','template_ids':[a['id']],'sticker_ids':[ids[0]],'client_token':'13'}
    response=admin.post('/api/orders',json=body)
    assert response.status_code==200,response.text
    order=response.json()
    assert (order['generation_count'],order['export_count'])==(12,13)
    for _ in range(12):asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    result=admin.get('/api/orders/'+order['id']).json()
    assert result['status']=='completed' and len(provider.calls)==12
    single=[a for a in result['artifacts'] if a['kind']=='sticker']
    assert len(single)==13 and single[-1]['path']=='验收_A1-01_2.png'
    second=admin.post('/api/orders',json={**body,'template_ids':[a['id'],b['id']],'client_token':'15'}).json()
    assert (second['generation_count'],second['export_count'])==(12,15)
    assert [e['copy_index'] for e in second['export_entries'] if e['code']=='A1-01']==[1,2,3]
    # The output cap counts occurrences, not unique generation work.
    many=[group(f'G{i}',ids)['id'] for i in range(30)]
    too_many=admin.post('/api/orders',json={**body,'template_ids':many,'client_token':'361'})
    assert too_many.status_code==422
    ok=admin.post('/api/orders',json={**body,'template_ids':many,'sticker_ids':[],'client_token':'360'})
    assert ok.status_code==200 and ok.json()['export_count']==360 and ok.json()['generation_count']==12


def test_template_snapshot_uses_current_sticker_image(context):
    app,admin,_,_=context
    s=sticker(admin,'CURRENT')
    t=admin.post('/api/templates',json={'code':'CURRENT','name':'Current','category':'general','sticker_ids':[s['id']]}).json()
    changed=admin.put('/api/stickers/'+s['id'],data={'code':'LATEST'},files={'file':('replacement.png',png((0,100,0,200)),'image/png')}).json()
    response=admin.post('/api/orders',json={'name':'snapshot','upload_id':upload(admin)['id'],'template_ids':[t['id']],'client_token':'snapshot'})
    assert response.status_code==200,response.text
    with app.state.db.transaction() as tx:
        frozen=tx.get('orders',response.json()['id'])['template_snapshots'][0]
        assert frozen['images'][0]['id']==changed['image']['id']
        assert frozen['images'][0]['code']=='LATEST'
        assert tx.get('template_revisions',t['id']+':1')['images'][0]['id']==s['image']['id']
