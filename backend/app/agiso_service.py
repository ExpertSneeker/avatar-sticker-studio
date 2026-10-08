"""Transactional integration state transitions; no network I/O in this module."""
from decimal import Decimal
from urllib.parse import urlencode
from .auth import token_hash
from .customer_orders import OpenOrder, create_customer_order, audit
from .db import uid
from .platforms import platform_of

RELEASE_OPS = {1300,1302,1303,1314}


def integration_id(shop_id,tid):
    return token_hash(shop_id+'\x00'+tid)


def event_family(event):
    """trade/refund/memo/... for any platform; Pinduoduo events predate the stored family."""
    return event.get('family') or ('trade' if event['topic']=='1' else 'memo' if event['topic']=='64' else 'refund')


def event_tid(event):
    payload=event.get('payload') or {}
    return event.get('tid') or payload.get('tid') or payload.get('Tid')


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
        from .agiso_protocol import aftersales_for
        if linked and aftersales_for(settings(),shop) and any(e['shop_id']==linked['shop_id'] and event_family(e)!='trade' and e['status'] in {'pending','blocked'} and event_tid(e)==linked['tid'] for e in tx.where('agiso_events','status','pending','blocked')):
            return False
        # Disabling future shop automation does not stop work on an existing order.
        return bool(shop and account_active(tx,shop) and not order.get('paused'))
    return True


def new_link(shop,tid,number,now):
    return {'id':integration_id(shop['id'],tid),'shop_id':shop['id'],'tid':tid,'order_number':number,'organization_id':shop['organization_id'],
            'customer_order_id':None,'open_status':'pending','message_status':'disabled','guest_url':None,'error':None,
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
            order.update(prior_state=order['state'],state='cancelled',paused=True)
            # Guest media re-checks the cancelled state on every request. Invalidate login sessions too.
            for session in tx.where('guest_sessions','order_id',order['id']):
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
    """Pinduoduo trade push (already complete in the payload)."""
    trade={'tid':payload['Tid'],'order_number':payload['OrderSn'],'paid_cents':int(Decimal(payload['PayAmount'])*100),
           'buyer_memo':payload.get('BuyerMemo') or '','remark':payload.get('Remark') or '','status':'paid','items':payload['ItemList']}
    return open_trade(tx,shop,trade,config,now)


def rule_key(shop,item):
    # Xiaohongshu order details carry SKU ids only; every other platform matches product + SKU.
    return item['sku_id'] if platform_of(shop)=='xhs' else (item['goods_id'],item['sku_id'])


def open_trade(tx,shop,trade,config,now):
    """Shared opening for every platform: SKU rules, quotas, number conflicts and refund holds."""
    key=integration_id(shop['id'],trade['tid'])
    link=tx.get('agiso_orders',key) or {**new_link(shop,trade['tid'],trade['order_number'],now),'platform':platform_of(shop)}
    if link.get('customer_order_id') or link['open_status']=='cancelled': return link
    link.update(order_number=trade['order_number'],paid_cents=trade['paid_cents'])
    update_aftersales(tx,link,now)
    if link.get('holds'):
        return link
    if trade.get('status','paid')!='paid':
        link.update(open_status='manual',error='order_'+trade['status'])
    elif not executable(tx,shop,now):
        link.update(open_status='disabled',error='shop_disabled')
    elif not trade['items']:
        link.update(open_status='manual',error='unmapped_sku')
    else:
        rules={rule_key(shop,r):r for r in shop.get('rules',[])}
        matched=[rules.get(rule_key(shop,item)) for item in trade['items']]
        if any(not r or not r['enabled'] for r in matched):
            link.update(open_status='manual',error='unmapped_sku')
        elif len({r['rerun_limit'] for r in matched})!=1:
            link.update(open_status='manual',error='conflicting_rules')
        else:
            generation=sum(r['generation_limit']*item['goods_count'] for r,item in zip(matched,trade['items']))
            final=sum(r['final_count']*item['goods_count'] for r,item in zip(matched,trade['items']))
            if not 1<=final<=generation<=360:
                link.update(open_status='manual',error='quota_exceeded')
            elif any(o.get('order_number')==trade['order_number'] for o in tx.where('orders','order_number',trade['order_number'])):
                link.update(open_status='manual',error='order_number_conflict')
            else:
                owner=tx.get('users',shop['owner'])
                body=OpenOrder(order_number=trade['order_number'],platform=platform_of(shop),shop_id=shop['id'],generation_limit=generation,final_count=final,rerun_limit=matched[0]['rerun_limit'],client_token='agiso:'+key)
                order=create_customer_order(tx,owner,body,now,shop)
                order['agiso_id']=key
                order['agiso_rule_snapshot']=[dict(r) for r in matched]
                if (trade.get('buyer_memo') or '').strip():order['buyer_memo']=trade['buyer_memo'].strip()[:2000]
                if (trade.get('remark') or '').strip():order['platform_remark']=trade['remark'].strip()[:2000]
                tx.put('orders',order)
                audit(tx,order,'agiso_open',owner['id'],now)
                link.update(customer_order_id=order['id'],open_status='opened',error=None,guest_url=config['origin']+'/guest?'+urlencode({'order_number':trade['order_number']}))
    tx.put('agiso_orders',link)
    return link


def apply_memo(tx,shop,payload,now):
    """买家备注修改通知：更新已开户订单的客户留言。"""
    key=integration_id(shop['id'],payload['tid'])
    link=tx.get('agiso_orders',key)
    order=tx.get('orders',(link or {}).get('customer_order_id') or '')
    if not order:return
    memo=(payload.get('buyer_memo') or '').strip()[:2000]
    if order.get('buyer_memo','')==memo:return
    order['buyer_memo']=memo
    order['version']=order.get('version',0)+1
    tx.put('orders',order)
    audit(tx,order,'agiso_memo','agiso',now)
