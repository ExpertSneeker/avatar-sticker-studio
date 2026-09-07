import asyncio,io,json
import pytest
from PIL import Image
from backend.tests.test_worker import context
from backend.tests.test_api import png,upload
from backend.tests.test_credits import member,fund
from backend.app.processing import overview,pack_set
from backend.app.schemas import PrintSettings


def create(client,code,count,scope='public'):
    response=client.post('/api/templates',data={'code':code,'name':code,'category':'general','scope':scope},files=[('files',(f'{i}.png',png(),'image/png')) for i in range(count)])
    assert response.status_code==200,response.text
    return response.json()


def test_actual_counts_snapshot_billing_prints_and_overview(context):
    app,admin,_,provider=context;staff,user=member(admin,app);fund(admin,user,14)
    public=create(admin,'SINGLE',1);private=create(staff,'A1-13',13,'personal')
    def submit(token):
        return staff.post('/api/orders',json={'upload_id':upload(staff)['id'],'name':token,'template_ids':[public['id'],private['id']],'print_settings':{},'client_token':token})
    first=submit('old');assert first.status_code==200,first.text
    o=first.json();assert o['total']==14
    assert staff.get('/api/credits').json()['wallet']['frozen']==14
    kept=private['images'][:2]
    edit=staff.put('/api/templates/'+private['id'],data={'code':private['code'],'name':private['name'],'category':'general','existing_ids':json.dumps([im['id'] for im in kept]),'image_order':json.dumps([{'id':im['id']} for im in reversed(kept)])})
    assert edit.status_code==200,edit.text
    assert len(edit.json()['images'])==2 and edit.json()['images'][0]['id']==kept[1]['id']
    for _ in range(14):asyncio.run(app.state.worker.execute(app.state.worker.claim()))
    result=staff.get('/api/orders/'+o['id']).json()
    assert result['status']=='completed',result
    assert len(provider.calls)==14 and result['total']==14
    assert staff.get('/api/credits').json()['wallet']['spent']==14
    assert {a['set_code'] for a in result['artifacts'] if a['kind']=='print'}=={'SINGLE','A1-13'}
    preview=next(a for a in result['artifacts'] if a['kind']=='overview')
    assert Image.open(io.BytesIO(staff.get(preview['url']).content)).size==(1024,1280)
    with app.state.db.transaction() as tx:
        assert len(tx.get('orders',o['id'])['template_snapshots'][1]['images'])==13
        assert len(tx.get('template_revisions',private['id']+':1')['images'])==13
    fund(admin,user,3,'second');assert submit('new').json()['total']==3


def test_empty_sets_and_invalid_order_are_rejected_without_orphan_files(context):
    app,admin,_,_=context
    response=admin.post('/api/templates',data={'code':'EMPTY','name':'Empty','category':'general'})
    assert response.status_code==422
    t=create(admin,'EDIT',3)
    before=set((app.state.db.root/'assets').iterdir())
    bad=admin.put('/api/templates/'+t['id'],data={'code':'EDIT','name':'Edit','category':'general','existing_ids':json.dumps([t['images'][0]['id']]),'image_order':json.dumps([{'file_index':0},{'file_index':0}])},files=[('files',('new.png',png(),'image/png'))])
    assert bad.status_code==422
    assert set((app.state.db.root/'assets').iterdir())==before
    assert len(admin.get('/api/templates').json()[0]['images'])==3


def test_large_order_rejected_before_reservation_or_job_creation(context):
    app,admin,_,_=context
    sets=[create(admin,f'LARGE-{i}',100) for i in range(4)]
    response=admin.post('/api/orders',json={'upload_id':upload(admin)['id'],'name':'too many','template_ids':[t['id'] for t in sets],'print_settings':{},'client_token':'too-many'})
    assert response.status_code==422
    with app.state.db.transaction() as tx:
        assert not tx.all('orders') and not tx.all('generations')


def test_variable_overview_groups_start_on_separate_rows_and_leave_white_cells():
    red=png((255,0,0,255));blue=png((0,0,255,255))
    image=Image.open(io.BytesIO(overview([red]+[blue]*5,'',[1,5])))
    assert image.size==(1024,768)
    assert image.getpixel((128,128))==(255,0,0)
    assert image.getpixel((384,128))==(255,255,255)
    assert image.getpixel((128,384))==(0,0,255)
    assert image.getpixel((128,640))==(0,0,255)
    assert image.getpixel((384,640))==(255,255,255)
    with pytest.raises(ValueError):overview([red],'',[2])
    assert len(pack_set([red],'Single','ONE',PrintSettings()))==1
