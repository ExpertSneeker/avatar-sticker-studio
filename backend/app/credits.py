"""Integer production credits. All mutation functions run in the caller's transaction."""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from .db import uid


def timestamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def wallet(user):
    return {'available':0,'frozen':0,'spent':0,'version':0,**user.get('credits',{}),'exempt':user['role']=='admin'}


def record(tx, owner, event, available, frozen, now, actor=None, reason='', generation=None):
    user=tx.get('users',owner);before=wallet(user)
    state={key:before[key] for key in ('available','frozen','spent','version')}
    state['available']+=available;state['frozen']+=frozen
    state['spent']+=int(event=='charge');state['version']+=1
    if state['available']<0 or state['frozen']<0:
        raise HTTPException(409,'可用积分不足，请联系管理员添加积分')
    user['credits']=state;tx.put('users',user)
    entry={'id':uid(),'owner':owner,'created_at':timestamp(now),'event':event,'available_delta':available,'frozen_delta':frozen,'available_after':state['available'],'frozen_after':state['frozen'],'amount':1 if generation else abs(available),'actor':actor,'reason':reason}
    if generation:
        entry.update(generation_id=generation['id'],order_id=generation['order_id'],item_id=generation['item_id'])
    tx.put('credit_ledger',entry)
    return wallet(user)


def reserve(tx, item, now):
    user=tx.get('users',item['owner'])
    generation={'id':uid(),'owner':item['owner'],'item_id':item['id'],'order_id':item['order_id'],'created_at':timestamp(now),'status':'exempt' if user['role']=='admin' else 'reserved'}
    if generation['status']=='reserved':
        record(tx,item['owner'],'reserve',-1,1,now,generation=generation)
    tx.put('generations',generation)
    item['generation_id']=generation['id']
    return generation


def settle(tx, generation_id, outcome, now, actor=None, reason=''):
    generation=tx.get('generations',generation_id or '')
    if generation and generation['status']=='released' and outcome=='charge':
        raise HTTPException(409, '已释放的生图记录不能重新发布，请重新提交生成')
    if not generation or generation['status'] in {'exempt','charged','released'}:
        return
    if generation['status'] not in {'reserved','review'}:
        raise HTTPException(409,'积分结算状态异常')
    record(tx,generation['owner'],outcome,1 if outcome=='release' else 0,-1,now,actor,reason,generation)
    generation.update(status='charged' if outcome=='charge' else 'released',settled_at=timestamp(now))
    tx.put('generations',generation)


def progress(tx, item, now):
    generation=tx.get('generations',item.get('generation_id',''))
    if not generation:
        return
    if item.get('fal_request_id'):
        generation['request_id']=item['fal_request_id']
    if generation['status'] in {'reserved','review'}:
        if item['status']=='unknown':generation['status']='review'
        elif item['status'] in {'running','queued'}:generation['status']='reserved'
        elif item['status']=='failed':
            # Human resolution of an unknown request deliberately calls no progress.
            settle(tx,generation['id'],'release',now)
            return
    tx.put('generations',generation)


def idempotent(tx, actor, token, payload):
    key=hashlib.sha256((actor+':'+token).encode()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    previous=tx.get('credit_operations',key)
    if previous and previous['fingerprint']!=fingerprint:
        raise HTTPException(409,'此操作编号已用于其他积分操作')
    return key,fingerprint,previous


def adjust(tx, actor, owner, data, now):
    key,fingerprint,previous=idempotent(tx,actor['id'],data.client_token,{'owner':owner,**data.model_dump()})
    if previous:return previous['wallet']
    user=tx.get('users',owner)
    if not user:raise HTTPException(404,'账号不存在')
    before=wallet(user)
    if before['exempt']:raise HTTPException(409,'管理员免扣积分，无需调整余额')
    if before['version']!=data.expected_version:raise HTTPException(409,'积分已变化，请刷新后重新确认')
    delta=data.amount if data.operation=='add' else data.amount-before['available']
    result=record(tx,owner,'adjust',delta,0,now,actor['id'],data.reason)
    tx.put('credit_operations',{'id':key,'fingerprint':fingerprint,'wallet':result})
    return result


def manual_settle(tx, actor, generation_id, data, now):
    key,fingerprint,previous=idempotent(tx,actor['id'],data.client_token,{'generation_id':generation_id,**data.model_dump()})
    if previous:return previous['wallet']
    generation=tx.get('generations',generation_id)
    if not generation or generation['status']!='review':raise HTTPException(409,'此生图积分不处于待核对状态')
    item=tx.get('items',generation['item_id'])
    if item and item.get('generation_id')==generation_id:
        if item['status'] in {'running','queued'}:raise HTTPException(409,'原请求正在恢复，请等待查询完成')
        item.update(status='failed',remote_reserved=False,error='管理员已核对原请求积分；可按需重新生成')
        tx.put('items',item)
    settle(tx,generation_id,data.outcome,now,actor['id'],data.reason)
    result=wallet(tx.get('users',generation['owner']))
    tx.put('credit_operations',{'id':key,'fingerprint':fingerprint,'wallet':result})
    return result


def report(tx, owner, now, days=30, offset=0, limit=50):
    user=tx.get('users',owner)
    if not user:raise HTTPException(404,'账号不存在')
    cutoff=timestamp(now-days*86400) if days else ''
    entries=[e for e in tx.all('credit_ledger') if e['owner']==owner and e['created_at']>=cutoff]
    entries.reverse()
    pending=[g for g in tx.all('generations') if g['owner']==owner and g['status']=='review']
    return {'wallet':wallet(user),'entries':entries[offset:offset+limit],'total':len(entries),'period_spent':sum(e['event']=='charge' for e in entries),'pending':pending}


def cleanup_credits(tx, order_ids, now, actor):
    for generation in tx.all('generations'):
        if generation['order_id'] in order_ids:
            if generation['status']=='review':
                raise HTTPException(409,'订单包含尚未核对的积分，请先由管理员完成核对')
            settle(tx,generation['id'],'release',now,actor,'订单清理释放未消耗积分')
            tx.delete('generations',generation['id'])
