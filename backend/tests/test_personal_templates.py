"""Legacy personal templates are promoted without rewriting historical revisions."""
from backend.tests.test_worker import context
from backend.tests.test_api import png
from backend.tests.test_credits import member
from backend.app.db import Database
from backend.app.storage import save_asset


def test_personal_templates_migrate_public_idempotently(context):
    app,admin,_,_=context
    alice,a=member(admin,app,'alice');bob,b=member(admin,app,'bobby')
    with app.state.db.transaction() as tx:
        tx.delete('migrations','public-stickers-v1')
        asset=save_asset(app.state.db,tx,png(),a['id'],'template')
        asset['scope']='personal';tx.put('assets',asset)
        legacy={'id':'legacy','code':'OLD','name':'旧套装','category':'animal','active':True,'revision':2,'scope':'personal','owner':a['id'],'images':[{'id':asset['id'],'url':asset['url'],'position':1}]}
        tx.put('templates',legacy)
        history={**legacy,'id':'legacy:1','revision':1,'template_id':'legacy'}
        tx.put('template_revisions',history)
        tx.put('templates',{**legacy,'id':'shared','code':'OTHER'})
    Database(app.state.db.root)
    with app.state.db.transaction() as tx:
        migrated=tx.get('templates','legacy')
        assert migrated['id']=='legacy' and migrated['revision']==2
        assert migrated['scope']=='public' and migrated['owner'] is None
        assert migrated['sticker_ids']==tx.get('templates','shared')['sticker_ids']
        assert len(tx.all('stickers'))==1
        assert tx.get('template_revisions','legacy:1')==history
        assert tx.get('assets',asset['id'])['owner'] is None
        sticker_id=migrated['sticker_ids'][0]
    assert bob.get(asset['url']).status_code==200
    assert bob.get('/api/templates').json()[0]['images'][0]['sticker_id']==sticker_id
    assert alice.patch('/api/templates/legacy',json={'active':False}).status_code==403
    Database(app.state.db.root)
    with app.state.db.transaction() as tx:
        assert len(tx.all('stickers'))==1 and tx.get('templates','legacy')['sticker_ids']==[sticker_id]
