"""SKU defaults update configured rules once, preserving all order snapshots."""
from copy import deepcopy
import pytest
from backend.app.db import Database


@pytest.mark.parametrize('name,expected',[
    ('1张',(3,1,1)),('6个',(8,6,3)),('12张',(16,12,6)),
    ('18个',(24,18,7)),('18张赠6个',(24,18,7)),('24个',(30,24,9)),('30张',(35,30,12)),('36个',(42,36,15)),
    ('42张',(50,42,18)),('6张加赠1张，42个套餐',(50,42,18)),
    ('16张',None),('61个',None),('1.6张',None),('10张',None),('6套',None),
])
def test_spec_defaults(name,expected):
    from backend.app.sku_defaults import spec_quotas
    assert spec_quotas(name)==expected


def test_existing_shops_migrate_once_without_changing_orders_or_other_config(tmp_path):
    db=Database(tmp_path)
    rule={'goods_id':'1','sku_id':'2','goods_name':'商品','sku_name':'36张','generation_limit':10,'final_count':10,'rerun_limit':2,'enabled':False}
    untouched={**rule,'sku_id':'3','sku_name':'16张'}
    with db.transaction() as tx:
        tx.delete('migrations','sku-spec-defaults-v1')
        for key,org in [('a','org-a'),('b','org-b')]:
            tx.put('agiso_shops',{'id':key,'organization_id':org,'owner':'user','enabled':False,'rules':[rule,untouched],'token':'synthetic'})
        order={'id':'o','generation_limit':10,'final_count':10,'rerun_limit':2,'version':5,'state':'draft'}
        tx.put('orders',order)
    db.close()
    db=Database(tmp_path)
    with db.transaction() as tx:
        for key in ('a','b'):
            s=tx.get('agiso_shops',key)
            assert s['enabled'] is False and s['token']=='synthetic'
            assert s['rules']==[{**rule,'generation_limit':42,'final_count':36,'rerun_limit':15,'enabled':True},{**untouched,'enabled':True}]
        assert tx.get('orders','o')==order
        s=tx.get('agiso_shops','a');s['rules'][0].update(generation_limit=45,enabled=False);tx.put('agiso_shops',s)
        before=deepcopy(tx.all('agiso_shops'))
    db.close()
    db=Database(tmp_path)
    with db.transaction() as tx:
        assert tx.all('agiso_shops')==before
        assert tx.get('migrations','sku-spec-defaults-v1')
    db.close()
