from backend.tests.test_worker import context
from backend.tests.test_library import stickers
from backend.app.db import Database
from backend.app.library import snapshot


def test_status_actions_are_retired_including_batch(context):
    _,admin,_,_=context
    s=stickers(admin,['LIVE']).json()[0]
    t=admin.post('/api/templates',json={'code':'LIVE','name':'Live','sticker_ids':[s['id']]}).json()
    for kind,id in [('stickers',s['id']),('templates',t['id'])]:
        assert admin.patch('/api/'+kind+'/'+id,json={'active':False}).status_code==410
    assert admin.post('/api/stickers/batch',json={'ids':[s['id']],'action':'update','active':False}).status_code==422
    assert admin.get('/api/stickers').json()[0]['active'] is True
    assert admin.get('/api/templates').json()[0]['available'] is True


def test_status_migration_preserves_deleted_resources_and_history(context):
    app,admin,_,_=context
    a,b=stickers(admin,['OLD','DELETED']).json()
    t=admin.post('/api/templates',json={'code':'OLD','name':'Old','sticker_ids':[a['id']]}).json()
    admin.delete('/api/stickers/'+b['id'])
    with app.state.db.transaction() as tx:
        tx.delete('migrations','library-always-available-v1')
        for kind,id in [('stickers',a['id']),('templates',t['id'])]:
            value=tx.get(kind,id);value.update(active=False,revision=2)
            tx.put(kind,value);snapshot(tx,kind,value)
    Database(app.state.db.root)
    Database(app.state.db.root)
    with app.state.db.transaction() as tx:
        for kind,id in [('stickers',a['id']),('templates',t['id'])]:
            assert tx.get(kind,id)['active'] is True
            assert tx.get(kind,id)['revision']==3
            assert tx.get(kind[:-1]+'_revisions',id+':2')['active'] is False
        assert tx.get('stickers',b['id'])['deleted']
        assert tx.get('stickers',b['id'])['active'] is False
