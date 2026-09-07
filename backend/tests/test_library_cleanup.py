from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from backend.app.db import Database
from backend.app.maintenance import cleanup_plan, account_deletion_plan


def test_archived_sticker_revision_protects_asset_from_date_cleanup(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        tx.put('orders', {'id':'order','owner':'member','avatar_id':'avatar','name':'old','created_at':'2020-01-01T00:00:00+00:00'})
        tx.put('assets', {'id':'shared','owner':'member','kind':'result','order_id':'order','file':'shared.png'})
        tx.put('sticker_revisions', {'id':'s:1','image':{'id':'shared'}})
        _, records, _ = cleanup_plan(db, tx, datetime(2026,1,1,tzinfo=timezone.utc))
        assert records['assets'] == []


def test_shared_library_survives_member_deletion_and_blocks_bad_ownership(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        tx.put('users', {'id':'member','role':'member'})
        tx.put('assets', {'id':'shared','owner':None,'kind':'template','file':'shared.png'})
        tx.put('stickers', {'id':'s','image':{'id':'shared'}})
        _, records, paths = account_deletion_plan(tx,'member')
        assert records['assets'] == [] and paths == []
        tx.put('assets', {'id':'shared','owner':'member','kind':'template','file':'shared.png'})
        with pytest.raises(HTTPException) as error:
            account_deletion_plan(tx,'member')
        assert error.value.status_code == 409


def test_legacy_personal_revision_survives_creator_deletion(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        tx.put('users', {'id':'member','role':'member'})
        tx.put('assets', {'id':'shared','owner':None,'kind':'template','file':'shared.png'})
        legacy = {'id':'legacy:1','scope':'personal','owner':'member','images':[{'id':'shared'}]}
        tx.put('template_revisions', legacy)
        tx.put('stickers', {'id':'s','image':{'id':'shared'}})
        _, records, paths = account_deletion_plan(tx,'member')
        assert records['template_revisions'] == records['assets'] == []
        assert paths == []
        assert tx.get('template_revisions','legacy:1') == legacy
