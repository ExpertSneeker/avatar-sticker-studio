"""Transactional integration state transitions; no network I/O in this module."""
from decimal import Decimal
from urllib.parse import urlencode
from .auth import token_hash
from .customer_orders import OpenOrder, create_customer_order, audit
from .db import uid

RELEASE_OPS = {1300,1302,1303,1314}


def integration_id(shop_id,tid):
    return token_hash(shop_id+'\x00'+tid)


def account_active(tx,shop):
    owner=tx.get('users',shop['owner'])
    org=tx.get('organizations',shop['organization_id'])
    return bool(owner and owner.get('active') and owner.get('organization_id')==shop['organization_id'] and org and org.get('active'))


def executable(tx,shop,now):
    return bool(shop and shop.get('enabled') and shop.get('token') and shop.get('expires_at',0)>now and account_active(tx,shop))


def order_allowed(tx,order):
    """Apply integration holds without changing the existing manual pause flag."""
    if not order or order.get('state')=='cancelled' or order.get('integration_holds'):
        return False
    if order.get('agiso_id'):
        linked=tx.get('agiso_orders',order['agiso_id'])
        shop=tx.get('agiso_shops',linked['shop_id']) if linked else None
        from .agiso_protocol import settings
        if linked and settings()['aftersales_enabled'] and any(e['shop_id']==linked['shop_id'] and e['topic']!='1' and e['status'] in {'pending','blocked'} and e['payload'].get('tid')==linked['tid'] for e in tx.all('agiso_events')):
            return False
        # Disabling future shop automation does not stop work on an existing order.
        return bool(shop and account_active(tx,shop) and not order.get('paused'))
    return True


def new_link(shop,tid,number,now):
    return {'id':integration_id(shop['id'],tid),'shop_id':shop['id'],'tid':tid,'order_number':number,'organization_id':shop['organization_id'],
            'customer_order_id':None,'open_status':'pending','message_status':'pending','guest_url':None,'error':None,
            'created_at':now,'entered_at':None,'send_attempts':0,'refunds':{}}


def update_aftersales(tx,link,now):
    refunds=list(link.get('refunds',{}).values())
    # A successful refund can never be undone by a later close/revoke notification.
    completed=[r for r in refunds if r['status']=='success']
    pending=[r for r in refunds if r['status']=='pending']
    paid=link.get('paid_cents')
    full=bool(completed and paid is not None and paid>0 and all(r['bill_type'] in {1,2} for r in completed)
              and sum(r['refund_fee'] for r in completed)==paid)
    manual=bool(completed and not full or any(r['status']=='manual' for r in refunds))
    holds={r['refund_id']:'aftersales' for r in pending}
    if manual: holds['manual_review']='aftersales_review'
    if full: holds['refunded']='aftersales_completed'
    link['holds']=holds
    if full: link['open_status']='cancelled';link['error']='refunded'
    elif manual: link['open_status']='manual';link['error']='aftersales_review'
    elif pending: link['open_status']='held';link['error']='aftersales_pending'
    elif link.get('customer_order_id') and link['open_status']=='held': link['open_status']='opened';link['error']=None
    order=tx.get('orders',link.get('customer_order_id') or '')
    if order:
        changed=order.get('integration_holds',{})!=holds
        order['integration_holds']=holds
        if full and order['state']!='cancelled':
            order.update(prior_state=order['state'],state='cancelled',paused=True,media_version=order['media_version']+1)
            # Existing guest media gate checks state/media version. Invalidate login sessions too.
            for session in tx.all('guest_sessions'):
                if session['order_id']==order['id']: tx.delete('guest_sessions',session['id'])
            changed=True
            audit(tx,order,'agiso_refund','agiso',now)
        if changed: order['version']+=1;tx.put('orders',order)
    tx.put('agiso_orders',link)


def apply_refund(tx,shop,payload,now):
    key=integration_id(shop['id'],payload['tid'])
    link=tx.get('agiso_orders',key) or new_link(shop,payload['tid'],payload['tid'],now)
    previous=link['refunds'].get(payload['refund_id'])
    if previous and payload['modified']<=previous['modified']: return
    if previous and previous['status']=='success': return
    status='success' if payload['operation']==1304 else 'released' if payload['operation'] in RELEASE_OPS else 'pending'
    if payload['bill_type'] not in {1,2}: status='manual'
    link['refunds'][payload['refund_id']]={**payload,'status':status}
    update_aftersales(tx,link,now)


def apply_trade(tx,shop,payload,config,now):
    key=integration_id(shop['id'],payload['Tid'])
    link=tx.get('agiso_orders',key) or new_link(shop,payload['Tid'],payload['OrderSn'],now)
    if link.get('customer_order_id') or link['open_status']=='cancelled': return link
    link.update(order_number=payload['OrderSn'],paid_cents=int(Decimal(payload['PayAmount'])*100))
    update_aftersales(tx,link,now)
    if link.get('holds'):
        return link
    if not executable(tx,shop,now):
        link.update(open_status='disabled',error='shop_disabled')
    else:
        rules={(r['goods_id'],r['sku_id']):r for r in shop.get('rules',[])}
        matched=[rules.get((item['goods_id'],item['sku_id'])) for item in payload['ItemList']]
        if any(not r or not r['enabled'] for r in matched):
            link.update(open_status='manual',error='unmapped_sku')
        elif len({r['rerun_limit'] for r in matched})!=1:
            link.update(open_status='manual',error='conflicting_rules')
        else:
            generation=sum(r['generation_limit']*item['goods_count'] for r,item in zip(matched,payload['ItemList']))
            final=sum(r['final_count']*item['goods_count'] for r,item in zip(matched,payload['ItemList']))
            if not 1<=final<=generation<=360:
                link.update(open_status='manual',error='quota_exceeded')
            elif any(o.get('order_number')==payload['OrderSn'] for o in tx.all('orders')):
                link.update(open_status='manual',error='order_number_conflict')
            else:
                owner=tx.get('users',shop['owner'])
                body=OpenOrder(order_number=payload['OrderSn'],generation_limit=generation,final_count=final,rerun_limit=matched[0]['rerun_limit'],client_token='agiso:'+key)
                order=create_customer_order(tx,owner,body,now)
                order['agiso_id']=key
                order['agiso_rule_snapshot']=[dict(r) for r in matched]
                tx.put('orders',order)
                audit(tx,order,'agiso_open',owner['id'],now)
                link.update(customer_order_id=order['id'],open_status='opened',error=None,guest_url=config['origin']+'/guest?'+urlencode({'order_number':payload['OrderSn']}))
                tx.put('agiso_outbox',{'id':key,'integration_id':key,'shop_id':shop['id'],'status':'pending','attempts':0,'next_at':now,'lease_until':0})
    tx.put('agiso_orders',link)
    return link
