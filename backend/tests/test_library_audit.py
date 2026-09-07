from backend.app.db import Database
from deploy.audit_public_library import audit, compare


def test_audit_account_hash_allows_permission_only_and_detects_deletion(tmp_path):
    db=Database(tmp_path)
    account={'id':'member','password_hash':'sensitive-hash','active':True,'credits':{'available':8},'can_edit_library':False}
    with db.transaction() as tx:
        tx.put('users',account)
    baseline=audit(tmp_path)
    assert 'sensitive-hash' not in str(baseline)
    with db.transaction() as tx:
        tx.put('users',{**account,'can_edit_library':True})
    assert compare(baseline,audit(tmp_path))==[]
    with db.transaction() as tx:
        tx.put('users',{**account,'credits':{'available':9}})
    assert 'account membership or state changed beyond library permission' in compare(baseline,audit(tmp_path))
    with db.transaction() as tx:
        tx.delete('users',account['id'])
    assert 'account membership or state changed beyond library permission' in compare(baseline,audit(tmp_path))
