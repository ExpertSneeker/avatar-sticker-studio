import asyncio,io,json
import pytest
from PIL import Image
from backend.tests.test_worker import context
from backend.tests.test_api import png,upload
from backend.tests.helpers import member, create_customer_order, generate_customer_order, customer_action, order_items, stored_order, run_all, submit_and_publish
from backend.app.processing import overview,pack_set
from backend.app.schemas import PrintSettings


def create(client,code,count,scope='public'):
    uploaded=client.post('/api/stickers',data={'codes':json.dumps([f'{code}-{i:02}' for i in range(count)]),'category':'general'},files=[('files',(f'{i}.png',png(),'image/png')) for i in range(count)])
    assert uploaded.status_code==200,uploaded.text
    response=client.post('/api/templates',json={'code':code,'name':code,'category':'general','sticker_ids':[s['id'] for s in uploaded.json()]})
    assert response.status_code==200,response.text
    return response.json()


def test_actual_counts_snapshot_prints_and_overview(context):
    app,admin,_,provider=context;staff,user=member(admin,app)
    admin.patch('/api/admin/users/'+user['id']+'/library-permission',json={'can_edit_library':True})
    public=create(admin,'SINGLE',1);private=create(staff,'A1-13',13)
    o,_=create_customer_order(staff,'old',14)
    o=generate_customer_order(staff,o,template_ids=[public['id'],private['id']])
    assert len(order_items(app,o))==14
    kept=private['images'][:2]
    edit=staff.put('/api/templates/'+private['id'],json={'code':'A2-14','name':private['name'],'category':'general','sticker_ids':[im['sticker_id'] for im in reversed(kept)]})
    assert edit.status_code==200 and len(edit.json()['images'])==2
    run_all(app);result=submit_and_publish(app,staff,o)
    assert len(provider.calls)==14 and len(result['slots'])==14
    manifest=staff.get('/api/customer-orders/'+o['id']+'/manifest').json()
    assert manifest['files'] and all(a['kind']=='print' for a in manifest['files'])
    assert Image.open(io.BytesIO(staff.get('/api/assets/'+stored_order(app,o)['overview_id']).content)).size==(1024,1024)
    with app.state.db.transaction(readonly=True) as tx:
        assert len(tx.get('template_revisions',private['id']+':1')['images'])==13
    newer,_=create_customer_order(staff,'new',3)
    newer=generate_customer_order(staff,newer,template_ids=[public['id'],private['id']])
    assert len(newer['slots'])==3 and len(order_items(app,newer))==3
    assert any(s['sticker_code']=='A1-13-00' for s in result['slots'])
    conflict=staff.put('/api/templates/'+private['id'],json={'code':'single','name':'Collision','category':'general','sticker_ids':[im['sticker_id'] for im in kept]})
    assert conflict.status_code==409
    with app.state.db.transaction(readonly=True) as tx:
        current=tx.get('templates',private['id']);assert current['code']=='A2-14' and current['revision']==2

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
    app,admin,_,_=context;sets=[create(admin,f'LARGE-{i}',100) for i in range(4)]
    o,_=create_customer_order(admin,'too many',360)
    response=customer_action(admin,o,'generate',avatars=[{'upload_id':upload(admin)['id'],'template_ids':[t['id'] for t in sets]}])
    assert response.status_code==422
    with app.state.db.transaction(readonly=True) as tx:
        assert not tx.all('items') and not tx.all('generations')
        assert tx.get('orders',o['id'])['state']=='draft'

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
