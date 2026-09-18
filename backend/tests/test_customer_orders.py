"""Customer order invariants exercised through HTTP with an unpaid local provider."""
import asyncio
import hashlib
import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_api import png, upload
from backend.tests.test_mixed_stickers import sticker


def opened(client, number='ORDER-001', **kw):
    response=client.post('/api/customer-orders',json={'order_number':number,'generation_limit':4,'final_count':2,'rerun_limit':1,'notes':'private note','client_token':number,**kw})
    assert response.status_code==200,response.text
    return response.json()


def action(client, order, name, **kw):
    return client.post('/api/customer-orders/'+order['id']+'/'+name,json={'client_token':name+str(order['version']),'expected_version':order['version'],**kw})


def generate(client, order, sid, count=2):
    body={'avatars':[{'upload_id':upload(client)['id'],'template_ids':[],'sticker_ids':[sid]*count}]}
    pre=action(client,order,'preflight',**body)
    assert pre.status_code==200,pre.text
    assert pre.json()=={'avatar_count':1,'selection_count':count,'generation_count':1}
    result=action(client,order,'generate',**body)
    assert result.status_code==200,result.text
    return result.json()


def run(app):
    item=app.state.worker.claim()
    assert item
    asyncio.run(app.state.worker.execute(item))
    return item


def test_open_idempotency_and_validation(context):
    app,c,_,_=context
    o=opened(c)
    assert o['state']=='draft' and o['version']==1 and o['notes']=='private note'
    assert opened(c)['id']==o['id']
    assert c.post('/api/customer-orders',json={'order_number':'ORDER-001','generation_limit':4,'final_count':2,'rerun_limit':1,'client_token':'other'}).status_code==409
    assert c.post('/api/customer-orders',json={'order_number':'bad','generation_limit':1,'final_count':2,'rerun_limit':0,'client_token':'bad'}).status_code==422


def test_duplicates_independent_rerun_selection_and_print_only_delivery(context):
    app,c,_,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id'])
    assert len(o['slots'])==2
    run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    a,b=o['slots']; assert a['selected_version_id']==b['selected_version_id']
    initial=a['selected_version_id']
    result=action(c,o,'slots/'+a['id']+'/rerun'); assert result.status_code==200,result.text
    o=result.json(); assert o['slots'][0]['reruns_reserved']==1
    run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    assert len(provider.calls)==2
    a,b=o['slots']; assert a['pending_version_id'] and b['selected_version_id']==initial and len(b['versions'])==1
    assert action(c,o,'submit',slot_ids=[a['id'],b['id']]).status_code==409
    o=action(c,o,'slots/'+a['id']+'/select',version_id=initial).json()
    assert o['slots'][0]['reruns_used']==1
    assert action(c,o,'slots/'+a['id']+'/rerun').status_code==409
    o=action(c,o,'submit',slot_ids=[b['id'],a['id']]).json()
    app.state.worker.publish(o['id'])
    o=c.get('/api/customer-orders/'+o['id']).json(); assert o['delivery_ready']
    manifest=c.get('/api/customer-orders/'+o['id']+'/manifest').json()
    assert manifest['files'] and all(f['kind']=='print' for f in manifest['files'])
    data=c.get('/api/customer-orders/'+o['id']+'/download.zip')
    assert data.status_code==200
    with zipfile.ZipFile(io.BytesIO(data.content)) as z: assert z.namelist()==[manifest['folder_name']+'/'+f['path'] for f in manifest['files']]


def test_guest_privacy_cancel_restore_submitted_and_media(context):
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    guest=TestClient(app)
    assert guest.post('/api/guest/login',json={'order_number':o['order_number']}).status_code==200
    g=guest.get('/api/guest/order').json()
    assert not {'notes','owner','watermark','organization_id','print_settings'} & g.keys()
    link=g['slots'][0]['versions'][0]['preview_url']
    media=guest.get(link); assert media.status_code==200 and media.headers['cache-control']=='no-store'
    assert Image_mode(media.content)=='RGB'
    assert guest.get('/api/assets/'+link.split('/')[-1].split('?')[0]).status_code in (401,404)
    o=c.get('/api/customer-orders/'+o['id']).json(); cancelled=action(c,o,'cancel').json()
    assert guest.get(link).status_code==404
    assert set(guest.get('/api/guest/order').json())=={'id','order_number','state'}
    o=action(c,cancelled,'restore').json(); assert guest.get(link).status_code==404
    o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json(); app.state.worker.publish(o['id'])
    g=guest.get('/api/guest/order').json(); assert 'slots' not in g and 'avatars' not in g
    assert guest.get(g['preview_url']).status_code==200
    assert guest.post('/api/guest/order/generate',json={'client_token':'late','expected_version':g['version'],'avatars':[]}).status_code in (409,422)


def Image_mode(data):
    from PIL import Image
    return Image.open(io.BytesIO(data)).mode


def test_guest_uploads_are_scoped_and_no_original_urls(context):
    app,c,_,_=context; o=opened(c)
    guest=TestClient(app); guest.post('/api/guest/login',json={'order_number':o['order_number']})
    data=png(); init={'filename':'avatar.png','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    u=guest.post('/api/guest/uploads/init',json=init).json()
    assert 'url' not in u
    assert guest.put('/api/guest/uploads/'+u['id'],content=data,headers={'Upload-Offset':'0'}).status_code==200
    done=guest.post('/api/guest/uploads/'+u['id']+'/complete'); assert done.status_code==200,done.text
    assert done.json()['preview_url'] and 'asset_id' not in done.json() and 'url' not in done.json()
    other=opened(c,'OTHER'); guest.post('/api/guest/login',json={'order_number':other['order_number']})
    assert guest.get('/api/guest/uploads/'+u['id']).status_code==404


def test_failed_rerun_releases_once_unknown_preserves_reservation_and_staff_recovery(context):
    from backend.app.providers import ProviderFailure
    app,c,_,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); sid=o['slots'][0]['id']
    o=action(c,o,'slots/'+sid+'/rerun').json()
    provider.error=ProviderFailure('no output','failed'); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); assert o['slots'][0]['reruns_reserved']==0 and o['slots'][0]['reruns_used']==0
    assert c.get('/api/customer-orders/'+o['id']).json()['version']==o['version']
    o=action(c,o,'slots/'+sid+'/rerun').json()
    provider.error=ProviderFailure('uncertain','unknown'); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); assert o['slots'][0]['reruns_reserved']==1
    assert action(c,o,'slots/'+sid+'/rerun').status_code==409
    assert action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).status_code==409
    response=action(c,o,'slots/'+sid+'/resolve',confirmed_ended=True); assert response.status_code==200,response.text
    assert response.json()['slots'][0]['reruns_reserved']==0


def test_staff_initial_failure_retry_zero_rerun_limit_and_cancel_admission(context):
    from backend.app.providers import ProviderFailure
    app,c,_,provider=context
    o=generate(c,opened(c,rerun_limit=0),sticker(c,'ONE')['id'])
    provider.error=ProviderFailure('failed','failed'); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    retry=action(c,o,'slots/'+o['slots'][0]['id']+'/retry'); assert retry.status_code==200,retry.text
    o=retry.json(); claimed=app.state.worker.claim(); assert claimed
    cancelled=action(c,o,'cancel'); assert cancelled.status_code==200,cancelled.text
    count=len(provider.calls); asyncio.run(app.state.worker.execute(claimed)); assert len(provider.calls)==count
    assert app.state.worker.claim() is None


def test_watermark_rotation_and_optimistic_idempotency(context):
    app,c,_,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); old=o['slots'][0]['versions'][0]['preview_url']
    before=len(provider.calls)
    c.patch('/api/account',json={'watermark':'NEW OWNER MARK'})
    preview=c.post('/api/customer-orders/watermarks/preview',json={'ids':[o['id']]}).json()
    body={'ids':[o['id']],'preview_token':preview['preview_token'],'client_token':'marks'}
    response=c.post('/api/customer-orders/watermarks',json=body); assert response.status_code==200,response.text
    assert c.post('/api/customer-orders/watermarks',json=body).json()=={'updated':1}
    assert c.get(old).status_code==404 and len(provider.calls)==before
    o=c.get('/api/customer-orders/'+o['id']).json()
    mutation={'client_token':'cancel-once','expected_version':o['version']}
    path='/api/customer-orders/'+o['id']+'/cancel'
    cancelled=c.post(path,json=mutation); assert cancelled.status_code==200,cancelled.text
    assert c.post(path,json=mutation).json()['version']==cancelled.json()['version']
    assert c.post(path,json={**mutation,'expected_version':999}).status_code==409


def test_seller_remark_is_idempotent_and_version_checked(context):
    app,c,_,_=context
    o=opened(c)
    body={'remark':'已补差价','client_token':'remark-1','expected_version':o['version']}
    first=c.post('/api/customer-orders/'+o['id']+'/remark',json=body)
    assert first.status_code==200,first.text
    assert first.json()['platform_remark']=='已补差价'
    repeat=c.post('/api/customer-orders/'+o['id']+'/remark',json=body)
    assert repeat.json()['version']==first.json()['version']
    assert c.post('/api/customer-orders/'+o['id']+'/remark',json={**body,'expected_version':999}).status_code==409


def test_seller_remark_edit_republishes_submitted_order(context):
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    submitted=action(c,o,'submit',slot_ids=[slot['id'] for slot in o['slots']])
    assert submitted.status_code==200,submitted.text
    o=submitted.json()
    app.state.worker.publish(o['id'])
    o=c.get('/api/customer-orders/'+o['id']).json()
    assert o['delivery_ready']
    before=o['delivery_version']
    result=action(c,o,'remark',remark='加急制作')
    assert result.status_code==200,result.text
    o=result.json()
    assert o['platform_remark']=='加急制作' and o['delivery_ready'] is False and o['delivery_version']>before
    app.state.worker.publish(o['id'])
    o=c.get('/api/customer-orders/'+o['id']).json()
    assert o['delivery_ready']


def test_login_throttle_survives_failed_transactions_and_inactive_org(context):
    app,c,_,_=context; o=opened(c)
    g=TestClient(app)
    for _ in range(12): assert g.post('/api/guest/login',json={'order_number':'invalid'}).status_code==401
    assert g.post('/api/guest/login',json={'order_number':'invalid'}).status_code==429
    with app.state.db.transaction() as tx:
        org=tx.get('organizations',o['organization_id']); org['active']=False;tx.put('organizations',org)
    other=TestClient(app,client=('different-client',1))
    assert other.post('/api/guest/login',json={'order_number':o['order_number']}).status_code==401


def test_staff_and_guest_media_authorities_are_separate(context):
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    other=opened(c,'OTHER')
    c.post('/api/guest/login',json={'order_number':other['order_number']})
    link=o['slots'][0]['versions'][0]['preview_url']
    assert link.startswith('/api/customer-orders/')
    assert c.get(link).status_code==200
    guest=TestClient(app); guest.post('/api/guest/login',json={'order_number':o['order_number']})
    assert guest.get(link).status_code==401
    glink=guest.get('/api/guest/order').json()['slots'][0]['versions'][0]['preview_url']
    assert c.get(glink).status_code==404
    c.post('/api/guest/logout')
    assert c.get(glink).status_code==401


def test_racing_mutations_reserve_only_one_rerun(context):
    from concurrent.futures import ThreadPoolExecutor
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); path='/api/customer-orders/'+o['id']+'/slots/'+o['slots'][0]['id']+'/rerun'
    def post(n):
        return c.post(path,json={'client_token':'race-'+str(n),'expected_version':o['version']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(post,range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    latest=c.get('/api/customer-orders/'+o['id']).json(); assert latest['slots'][0]['reruns_reserved']==1
    with app.state.db.transaction() as tx:
        assert len([i for i in tx.all('items') if i['order_id']==o['id']])==2


def test_cancel_during_render_and_publication_never_serves_stale_bytes(context,monkeypatch):
    from backend.app import guest_media, publication
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    g=TestClient(app); g.post('/api/guest/login',json={'order_number':o['order_number']})
    link=g.get('/api/guest/order').json()['slots'][0]['versions'][0]['preview_url']
    original=guest_media.render
    def interrupted(*args):
        data=original(*args)
        latest=c.get('/api/customer-orders/'+o['id']).json()
        assert action(c,latest,'cancel').status_code==200
        return data
    monkeypatch.setattr(guest_media,'render',interrupted)
    assert g.get(link).status_code==404
    monkeypatch.setattr(guest_media,'render',original)
    cancelled=c.get('/api/customer-orders/'+o['id']).json(); o=action(c,cancelled,'restore').json()
    o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json(); assert not o['delivery_ready']
    original_pack=publication.pack_set
    def cancelled_pack(*args):
        pages=original_pack(*args)
        latest=c.get('/api/customer-orders/'+o['id']).json()
        assert action(c,latest,'cancel').status_code==200
        return pages
    monkeypatch.setattr(publication,'pack_set',cancelled_pack)
    assert app.state.worker.publish(o['id']) is False
    assert c.get('/api/customer-orders/'+o['id']+'/manifest').status_code==409
    with app.state.db.transaction() as tx:
        assert not tx.get('orders',o['id'])['artifacts']


def test_zip_uses_safe_order_notes_folder_and_no_rerun_ceiling(context):
    app,c,_,_=context
    o=generate(c,opened(c,notes='客户 / A:首单',rerun_limit=1001),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json()
    app.state.worker.publish(o['id'])
    manifest=c.get('/api/customer-orders/'+o['id']+'/manifest').json()
    assert manifest['folder_name']=='ORDER-001_客户 _ A_首单'
    with zipfile.ZipFile(io.BytesIO(c.get('/api/customer-orders/'+o['id']+'/download.zip').content)) as archive:
        assert all(name.startswith(manifest['folder_name']+'/') for name in archive.namelist())


def test_multiple_avatars_use_separate_provider_references_and_repeated_templates(context):
    app,c,_,provider=context
    s=sticker(c,'ONE')
    t=c.post('/api/templates',json={'code':'SET','name':'Set','category':'general','sticker_ids':[s['id']]}).json()
    a=upload(c)
    from backend.tests.test_api import upload as upload_image
    # Same content with distinct filename still represents a distinct avatar record.
    data=png((0,100,0,200))
    init=c.post('/api/uploads/init',json={'filename':'second.png','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}).json()
    c.put('/api/uploads/'+init['id'],content=data,headers={'Upload-Offset':'0'})
    b=c.post('/api/uploads/'+init['id']+'/complete').json()
    o=opened(c)
    avatars=[{'upload_id':a['id'],'template_ids':[t['id'],t['id']],'sticker_ids':[]},{'upload_id':b['id'],'template_ids':[],'sticker_ids':[s['id']]}]
    assert action(c,o,'preflight',avatars=avatars).json()=={'avatar_count':2,'selection_count':3,'generation_count':2}
    response=action(c,o,'generate',avatars=avatars); assert response.status_code==200,response.text
    run(app);run(app)
    assert provider.calls[0][1]!=provider.calls[1][1]
    with app.state.db.transaction() as tx:
        assert all(g['status']=='exempt' for g in tx.all('generations'))


def test_recovery_unknown_hold_not_double_consumed(context):
    from backend.app.worker import Worker
    app,c,clock,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json(); sid=o['slots'][0]['id'];o=action(c,o,'slots/'+sid+'/rerun').json()
    assert app.state.worker.claim()
    clock.value+=61
    worker=Worker(app.state.db,provider=provider,clock=clock)
    worker.recover();worker.recover()
    o=c.get('/api/customer-orders/'+o['id']).json()
    assert o['slots'][0]['status']=='unknown' and o['slots'][0]['reruns_reserved']==1 and o['slots'][0]['reruns_used']==0
    assert worker.claim() is None


def test_publication_failure_is_visible_and_can_repack_without_generation(context,monkeypatch):
    from backend.app import publication
    app,c,_,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']);run(app)
    o=c.get('/api/customer-orders/'+o['id']).json();o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json()
    real=publication.pack_set
    def broken(*args):raise ValueError('printing failed')
    monkeypatch.setattr(publication,'pack_set',broken)
    assert app.state.worker.publish(o['id']) is False
    o=c.get('/api/customer-orders/'+o['id']).json();assert o['processing_error'] and not o['delivery_ready']
    monkeypatch.setattr(publication,'pack_set',real)
    before=len(provider.calls)
    o=action(c,o,'repack').json();app.state.worker.publish(o['id'])
    assert c.get('/api/customer-orders/'+o['id']).json()['delivery_ready']
    assert len(provider.calls)==before


def test_saved_raw_reprocess_never_calls_generation_provider_again(context,monkeypatch):
    from backend.app import worker as worker_module
    app,c,_,provider=context
    o=generate(c,opened(c,rerun_limit=0),sticker(c,'ONE')['id'])
    original_decode=worker_module.decode
    calls=0
    def fail_final_decode(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:raise ValueError('local processing failure')
        return original_decode(*args,**kwargs)
    monkeypatch.setattr(worker_module,'decode',fail_final_decode)
    run(app)
    o=c.get('/api/customer-orders/'+o['id']).json();slot=o['slots'][0]
    assert slot['status']=='failed' and slot['raw_available']
    monkeypatch.setattr(worker_module,'decode',original_decode)
    response=action(c,o,'slots/'+slot['id']+'/reprocess');assert response.status_code==200,response.text
    before=len(provider.calls);run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    assert all(s['selected_version_id'] for s in o['slots']) and len(provider.calls)==before


def test_unlock_keeps_versions_and_quota_and_invalidates_delivery(context):
    app,c,_,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']);run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    version_ids=[s['selected_version_id'] for s in o['slots']]
    o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json();app.state.worker.publish(o['id'])
    o=c.get('/api/customer-orders/'+o['id']).json();overview=o['preview_url']
    o=action(c,o,'unlock').json();assert o['state']=='review' and not o['delivery_ready']
    assert [s['selected_version_id'] for s in o['slots']]==version_ids
    assert c.get(overview).status_code==404
    assert c.get('/api/customer-orders/'+o['id']+'/download.zip').status_code==409
    before=len(provider.calls)
    o=action(c,o,'submit',slot_ids=[s['id'] for s in reversed(o['slots'])]).json();app.state.worker.publish(o['id'])
    assert c.get('/api/customer-orders/'+o['id']).json()['delivery_ready']
    assert len(provider.calls)==before


def test_unicode_delivery_paths_fit_filesystem_byte_limits(context):
    app,c,_,_=context
    o=generate(c,opened(c,'订'*100,notes='客户🙂'*80),sticker(c,'ONE')['id']);run(app)
    o=c.get('/api/customer-orders/'+o['id']).json();o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json();app.state.worker.publish(o['id'])
    manifest=c.get('/api/customer-orders/'+o['id']+'/manifest').json()
    assert len(manifest['folder_name'].encode('utf-8'))<=220
    assert all(len(f['path'].encode('utf-8'))<=255 for f in manifest['files'])
    assert all(f['path'].startswith('page-') for f in manifest['files'])
    assert c.get('/api/customer-orders/'+o['id']+'/manifest').json()['folder_name']==manifest['folder_name']


def test_submit_rejects_failed_uncertain_cutout_even_with_old_selected_result(context):
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']);run(app)
    o=c.get('/api/customer-orders/'+o['id']).json();sid=o['slots'][0]['id'];o=action(c,o,'slots/'+sid+'/rerun').json()
    item=app.state.worker.claim()
    with app.state.db.transaction() as tx:
        current=tx.get('items',item['id']);current.update(status='failed',remote_reserved=False,cutout_inflight=True,error='uncertain cutout');tx.put('items',current)
    o=c.get('/api/customer-orders/'+o['id']).json()
    assert o['slots'][0]['selected_version_id'] and o['slots'][0]['needs_resolution'] and o['slots'][0]['reruns_reserved']==1
    assert action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).status_code==409


def test_cancel_during_generation_defers_new_cutout_until_restore(context,monkeypatch):
    from backend.app import worker as worker_module
    app,c,_,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id'])
    with app.state.db.transaction() as tx:
        config=tx.get('config','settings');config['cutout_api_key']='local-test-only';tx.put('config',config)
    class CancellingProvider:
        calls=0
        async def generate(self,**kwargs):
            self.calls+=1
            latest=c.get('/api/customer-orders/'+o['id']).json()
            assert action(c,latest,'cancel').status_code==200
            from PIL import Image
            output=io.BytesIO();Image.new('RGB',(1024,1024),(100,100,100)).save(output,'PNG')
            return output.getvalue()
    class Cutout:
        calls=0
        def __init__(self,*args):pass
        async def cutout(self,data):
            Cutout.calls+=1
            return png(size=(1024,1024))
    generator=CancellingProvider();app.state.worker.provider=generator
    monkeypatch.setattr(worker_module,'YeziProvider',Cutout)
    item=run(app)
    assert Cutout.calls==0
    with app.state.db.transaction() as tx:
        saved=tx.get('items',item['id'])
        assert saved['raw_result_id'] and saved['status']=='queued' and saved['processing_stage']=='postprocess'
        assert not saved.get('cutout_inflight')
    assert app.state.worker.claim() is None
    cancelled=c.get('/api/customer-orders/'+o['id']).json();assert action(c,cancelled,'restore').status_code==200
    run(app)
    assert Cutout.calls==1 and generator.calls==1
    assert c.get('/api/customer-orders/'+o['id']).json()['slots'][0]['status']=='completed'


def test_cancel_while_waiting_for_cutout_capacity_never_sends_request(context,monkeypatch):
    from backend.app import providers
    from backend.tests.test_providers import install
    from PIL import Image
    import httpx
    app,c,clock,provider=context
    o=generate(c,opened(c),sticker(c,'ONE')['id'])
    with app.state.db.transaction() as tx:
        config=tx.get('config','settings');config['cutout_api_key']='local-test-only';tx.put('config',config)
        for i in range(2):tx.put('cutout_calls',{'id':'busy-'+str(i),'expires':clock()+100})
    async def opaque(**kwargs):
        output=io.BytesIO();Image.new('RGB',(1024,1024),'red').save(output,'PNG');return output.getvalue()
    monkeypatch.setattr(provider,'generate',opaque)
    waits=[]
    async def cancelled_wait(delay):
        waits.append(delay)
        latest=c.get('/api/customer-orders/'+o['id']).json()
        assert action(c,latest,'cancel').status_code==200
        clock.value+=101
    monkeypatch.setattr(providers.asyncio,'sleep',cancelled_wait)
    requests=[]
    def receive(request):
        requests.append(request)
        if request.method=='POST':return httpx.Response(200,json={'status':200,'data':{'image':'https://media.yezisheji.com/cut.png'}})
        return httpx.Response(200,content=png(size=(1024,1024)))
    install(monkeypatch,receive)
    item=run(app)
    assert waits and not requests
    with app.state.db.transaction() as tx:
        value=tx.get('items',item['id'])
        assert value['status']=='queued' and value['raw_result_id'] and value['processing_stage']=='postprocess'
        assert not value.get('cutout_inflight') and not value.get('remote_reserved')


def test_submitted_overview_has_only_one_watermark(context):
    from PIL import Image, ImageChops
    from backend.app.storage import asset_bytes
    app,c,_,_=context
    o=generate(c,opened(c),sticker(c,'ONE')['id']); run(app)
    o=c.get('/api/customer-orders/'+o['id']).json()
    o=action(c,o,'submit',slot_ids=[s['id'] for s in o['slots']]).json()
    app.state.worker.publish(o['id'])
    guest=TestClient(app)
    guest.post('/api/guest/login',json={'order_number':o['order_number']})
    response=guest.get(guest.get('/api/guest/order').json()['preview_url'])
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    with app.state.db.transaction() as tx:
        order=tx.get('orders',o['id'])
        data=asset_bytes(app.state.db,tx.get('assets',order['overview_id']))
    expected=Image.open(io.BytesIO(data)).convert('RGB')
    expected.thumbnail((640,640),Image.Resampling.LANCZOS)
    actual=Image.open(io.BytesIO(response.content)).convert('RGB')
    assert ImageChops.difference(actual,expected).getbbox() is None
