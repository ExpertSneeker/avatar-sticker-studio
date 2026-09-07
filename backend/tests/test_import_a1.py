import hashlib
import pytest
from backend.app.db import Database
from backend.app.import_a1 import import_a1, MARKER
from backend.tests.test_api import png


def sources(tmp_path):
    folder = tmp_path / 'A1'
    folder.mkdir()
    for n in range(1, 13):
        (folder / f'A1-{n:02d}.png').write_bytes(png((n, 20, 30, 255)))
    return folder


def test_import_archives_old_preserves_history_and_is_idempotent(tmp_path):
    db = Database(tmp_path / 'data')
    folder = sources(tmp_path)
    old = {'id':'old', 'code':'MB-A', 'name':'old', 'revision':7, 'images':[], 'scope':'public', 'owner':None, 'active':True}
    historical = {**old, 'id':'old:7', 'template_id':'old'}
    with db.transaction() as tx:
        tx.put('templates', old)
        tx.put('template_revisions', historical)
        tx.put('orders', {'id':'historical-order', 'template_ids':['old']})
    result = import_a1(db, folder)
    assert result['archived_template_ids'] == ['old']
    with db.transaction() as tx:
        assert tx.get('template_revisions', 'old:7') == historical
        assert tx.get('orders', 'historical-order')['template_ids'] == ['old']
        assert tx.get('templates', 'old')['deleted']
        assert len(tx.all('stickers')) == len(tx.all('sticker_revisions')) == 12
        template = tx.get('templates', result['template_id'])
        assert template['name'] == '模板A' and len(template['sticker_ids']) == 12
        for n, image in enumerate(template['images'], 1):
            asset = tx.get('assets', image['id'])
            assert asset['owner'] is None
            assert (db.root / 'assets' / asset['file']).read_bytes() == (folder / f'A1-{n:02d}.png').read_bytes()
        before = tx.conn.execute('select * from records order by kind,id').fetchall()
    assert import_a1(db, folder)['already_imported']
    with db.transaction() as tx:
        assert tx.conn.execute('select * from records order by kind,id').fetchall() == before


def test_collisions_and_source_change_do_not_replace_active_template(tmp_path):
    db = Database(tmp_path / 'data')
    folder = sources(tmp_path)
    with db.transaction() as tx:
        tx.put('stickers', {'id':'conflict','code':'a1-03'})
    with pytest.raises(ValueError, match='collision'):
        import_a1(db, folder)
    with db.transaction() as tx:
        assert not tx.all('assets') and not tx.all('templates')
        tx.delete('stickers','conflict')
    result = import_a1(db, folder)
    (folder / 'A1-01.png').write_bytes(png((250, 0, 0, 255)))
    with pytest.raises(ValueError, match='source changed'):
        import_a1(db, folder)
    with db.transaction() as tx:
        assert tx.get('migrations', MARKER)['template_id'] == result['template_id']


def test_interrupted_staging_resumes_without_duplicate_assets(tmp_path, monkeypatch):
    db = Database(tmp_path / 'data')
    folder = sources(tmp_path)
    from backend.app.db import Transaction
    original = Transaction.put
    def fail(self, kind, doc):
        if kind == 'stickers':
            raise RuntimeError('interrupted switch')
        return original(self, kind, doc)
    monkeypatch.setattr(Transaction, 'put', fail)
    with pytest.raises(RuntimeError):
        import_a1(db, folder)
    with db.transaction() as tx:
        assert len(tx.all('assets')) == 12
        assert tx.all('stickers') == tx.all('templates') == []
    monkeypatch.setattr(Transaction, 'put', original)
    import_a1(db, folder)
    with db.transaction() as tx:
        assert len(tx.all('assets')) == len(tx.all('stickers')) == 12
    assert len(list((db.root / 'assets').glob('*.png'))) == 12


def test_import_retires_only_exclusive_migration_derived_stickers(tmp_path):
    from backend.app.library import migrate_library
    db = Database(tmp_path / 'data')
    folder = sources(tmp_path)
    with db.transaction() as tx:
        tx.delete('migrations', 'public-stickers-v1')
        def im(id):
            return {'id':id, 'url':'/api/assets/'+id, 'position':1}
        tx.put('stickers', {'id':'independent','code':'INDEPENDENT','image':im('independent-asset'),'active':True,'revision':1})
        base={'category':'general','name':'old','scope':'public','owner':None,'active':True,'revision':1}
        tx.put('templates', {**base,'id':'old','code':'MB-A','images':[im('exclusive'),im('reused'),im('independent-asset')]})
        tx.put('templates', {**base,'id':'other','code':'OTHER','active':False,'images':[im('reused')]})
        migrate_library(tx)
        derived=tx.get('migrations','public-stickers-v1')['derived_sticker_ids_by_template']
        assert 'independent' not in derived['old']
        exclusive,reused,_=tx.get('templates','old')['sticker_ids']
        revisions=tx.all('sticker_revisions')
    result=import_a1(db,folder)
    assert result['archived_sticker_ids']==[exclusive]
    with db.transaction() as tx:
        assert tx.get('stickers',exclusive)['deleted']
        assert not tx.get('stickers',reused).get('deleted')
        assert tx.get('stickers','independent')['active']
        assert all(tx.get('sticker_revisions',r['id'])==r for r in revisions)
