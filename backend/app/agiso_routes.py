"""Tenant-scoped management and authenticated, bounded Agiso push ingress."""
import hmac
import json
import os
import secrets
from urllib.parse import parse_qs, urlencode
from fastapi import HTTPException, Request, Response, Query
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from . import agiso_protocol as protocol
from .agiso_service import account_active, executable, integration_id, order_allowed
from .auth import token_hash
from .db import uid


def register_agiso(app,db,user):
    now=app.state.clock

    def scoped(tx,request,id,manage=False):
        actor=user(tx,request);shop=tx.get('agiso_shops',id)
        # Even superadmins cannot accidentally operate across an organization here.
        if not shop or shop['organization_id']!=actor.get('organization_id'):raise HTTPException(404,'店铺不存在')
        if manage and not can_manage(actor,shop):raise HTTPException(403,'需要店铺所属账号或组织管理员权限')
        return actor,shop

    def can_manage(actor,shop):
        return shop['owner']==actor['id'] or actor['role'] in {'org_admin','superadmin'}

    def shop_dto(tx,shop,actor):
        owner=tx.get('users',shop['owner']) or {}
        return {k:shop.get(k) for k in ('id','shop_id','shop_name','owner','organization_id','enabled','expires_at','last_event_at')} | {
            'owner_name':owner.get('display_name',''),'authorized':bool(shop.get('token') and shop.get('expires_at',0)>now()),'can_manage':can_manage(actor,shop)}

    def require_config():
        config=protocol.settings()
        if not config['configured']:raise HTTPException(409,'Agiso服务尚未配置完整')
        return config

    @app.get('/api/agiso/status')
    def status(request:Request):
        with db.transaction() as tx:user(tx,request)
        config=protocol.settings();origin=config['origin'] if 'STUDIO_AGISO_PUBLIC_URL' not in config['missing'] else None
        return {k:config[k] for k in ('configured','missing','aftersales_enabled')} | {
            'authorization_callback_url':origin+'/api/agiso/callback' if origin else None,'webhook_url':origin+'/api/agiso/webhook' if origin else None}

    @app.get('/api/agiso/shops')
    def shops(request:Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            return [shop_dto(tx,s,actor) for s in tx.all('agiso_shops') if s['organization_id']==actor.get('organization_id')]

    @app.post('/api/agiso/authorize')
    def authorize(request:Request,response:Response):
        config=require_config()
        with db.transaction() as tx:
            actor=user(tx,request)
            if not actor.get('organization_id'):raise HTTPException(409,'请先关联组织')
            state=secrets.token_urlsafe(32)
            browser_nonce=secrets.token_urlsafe(32)
            response.set_cookie('studio_agiso_oauth',browser_nonce,max_age=900,httponly=True,samesite='lax',secure=os.environ.get('STUDIO_SECURE_COOKIE')=='1',path='/api/agiso/callback')
            tx.put('agiso_oauth',{'id':token_hash(state),'owner':actor['id'],'organization_id':actor['organization_id'],'expires':now()+900,'used':False,'nonce_hash':token_hash(browser_nonce),'session_id':token_hash(request.cookies.get('studio_session',''))})
        return {'url':'https://aldspdd.agiso.com/#/authorize?'+urlencode({'appId':config['app_id'],'state':state})}

    @app.get('/api/agiso/callback')
    async def callback(request:Request,code:str='',state:str=''):
        try:
            config=require_config()
            if not code or len(code)>2048 or not state or len(state)>200:raise ValueError()
            with db.transaction() as tx:
                entry=tx.get('agiso_oauth',token_hash(state))
                if not entry or entry['used'] or entry['expires']<=now() or not hmac.compare_digest(entry.get('nonce_hash',''),token_hash(request.cookies.get('studio_agiso_oauth',''))):raise ValueError()
                session=tx.get('sessions',entry['session_id'])
                actor=tx.get('users',entry['owner'])
                if not session or session['expires']<=now() or session['user_id']!=entry['owner'] or not actor or not actor['active'] or entry['organization_id']!=actor.get('organization_id'):raise ValueError()
                if request.cookies.get('studio_session') and user(tx,request)['id']!=actor['id']:raise ValueError()
                entry['used']=True;tx.put('agiso_oauth',entry)
            authorization=await protocol.exchange(code,config,app.state.agiso_worker.transport,now())
            with db.transaction() as tx:
                current=tx.get('users',actor['id']);org=tx.get('organizations',entry['organization_id'])
                if not current or not current['active'] or current.get('organization_id')!=entry['organization_id'] or not org or not org['active']:raise ValueError()
                existing=next((s for s in tx.all('agiso_shops') if s['shop_id']==authorization['shop_id']),None)
                if existing and (existing['owner']!=actor['id'] or existing['organization_id']!=actor['organization_id']):raise ValueError()
                shop=existing or {'id':uid(),'owner':actor['id'],'organization_id':actor['organization_id'],'enabled':False,'rules':[],'last_event_at':None}
                shop.update(authorization);tx.put('agiso_shops',shop)
            response=RedirectResponse('/?agiso=connected',status_code=303)
            response.delete_cookie('studio_agiso_oauth',path='/api/agiso/callback')
            return response
        except Exception:
            response=RedirectResponse('/?agiso=error',status_code=303)
            response.delete_cookie('studio_agiso_oauth',path='/api/agiso/callback')
            return response

    @app.patch('/api/agiso/shops/{id}')
    def patch_shop(id:str,data:protocol.Enabled,request:Request):
        with db.transaction() as tx:
            actor,shop=scoped(tx,request,id,True)
            if data.enabled:
                require_config()
                if not shop.get('token') or shop.get('expires_at',0)<=now() or not account_active(tx,shop) or not any(r['enabled'] for r in shop['rules']):
                    raise HTTPException(409,'请先完成授权并启用至少一条规格规则')
            shop['enabled']=data.enabled;tx.put('agiso_shops',shop)
            return shop_dto(tx,shop,actor)

    @app.get('/api/agiso/shops/{id}/rules')
    def rules(id:str,request:Request):
        with db.transaction() as tx:
            _,shop=scoped(tx,request,id);return shop['rules']

    @app.put('/api/agiso/shops/{id}/rules')
    def save_rules(id:str,data:protocol.Rules,request:Request):
        with db.transaction() as tx:
            _,shop=scoped(tx,request,id,True)
            shop['rules']=[r.model_dump() for r in data.rules]
            if not any(r['enabled'] for r in shop['rules']):shop['enabled']=False
            tx.put('agiso_shops',shop);return shop['rules']

    @app.get('/api/agiso/shops/{id}/goods')
    async def goods(id:str,request:Request,page:int=Query(1,ge=1,le=10000),goods_name:str=Query('',max_length=200)):
        with db.transaction() as tx:
            _,shop=scoped(tx,request,id,True)
            if not account_active(tx,shop):raise HTTPException(409,'店铺所属账号不可用')
        config=protocol.settings()
        failure={'available':False,'goods':[],'total':0,'page':page,'message':'商品读取暂不可用，请从拼多多后台核对商品ID和规格ID后手动填写'}
        if not config['configured'] or not shop.get('token') or shop.get('expires_at',0)<=now():return failure
        try:
            fields={'page':str(page),'pageSize':'100'}
            if goods_name:fields['goodsName']=goods_name
            result=await protocol.api('Goods/List',fields,shop,config,app.state.agiso_worker.transport,now())
            data=result.get('Data')
            if result['IsSuccess'] is not True or not isinstance(data,dict) or type(data.get('total_count')) is not int or data['total_count']<0 or not isinstance(data.get('goods_list'),list) or len(data['goods_list'])>100:raise ValueError()
            rows=[]
            for row in data['goods_list']:
                if not isinstance(row,dict) or not isinstance(row.get('goods_name'),str) or not isinstance(row.get('sku_list'),list):raise ValueError()
                skus=[]
                for sku in row['sku_list']:
                    if not isinstance(sku,dict) or not isinstance(sku.get('spec'),str):raise ValueError()
                    skus.append({'sku_id':protocol.identifier(sku['sku_id']),'sku_name':sku['spec']})
                rows.append({'goods_id':protocol.identifier(row['goods_id']),'goods_name':row['goods_name'],'skus':skus})
            return {'available':True,'goods':rows,'total':data['total_count'],'page':page,'message':''}
        except Exception:return failure

    def retryable(tx,link,shop):
        job=tx.get('agiso_outbox',link['id']);order=tx.get('orders',link.get('customer_order_id') or '')
        return bool(job and job['status']=='failed' and job.get('retry_safe') and link['send_attempts']<5 and executable(tx,shop,now()) and order_allowed(tx,order) and not link.get('holds'))

    def order_dto(tx,link,shop,actor):
        row={k:link.get(k) for k in ('id','order_number','customer_order_id','open_status','message_status','guest_url','error','created_at','entered_at')}
        row['can_retry']=can_manage(actor,shop) and retryable(tx,link,shop)
        if link['message_status']=='pending':
            reason='shop_disabled' if not shop['enabled'] else 'authorization_expired' if shop.get('expires_at',0)<=now() else 'account_disabled' if not account_active(tx,shop) else 'aftersales_pending' if link.get('holds') else None
            if reason:row.update(message_status='blocked',error=reason)
        return row

    @app.get('/api/agiso/shops/{id}/orders')
    def orders(id:str,request:Request):
        with db.transaction() as tx:
            actor,shop=scoped(tx,request,id)
            return [order_dto(tx,o,shop,actor) for o in reversed(tx.all('agiso_orders')) if o['shop_id']==id]

    @app.post('/api/agiso/shops/{id}/orders/{order_id}/retry-message')
    def retry(id:str,order_id:str,request:Request):
        with db.transaction() as tx:
            _,shop=scoped(tx,request,id,True);link=tx.get('agiso_orders',order_id)
            if not link or link['shop_id']!=id:raise HTTPException(404,'记录不存在')
            if not retryable(tx,link,shop):raise HTTPException(409,'当前消息不能重试，请人工核对')
            job=tx.get('agiso_outbox',order_id);job.update(status='pending',next_at=now())
            link.update(message_status='pending');tx.put('agiso_outbox',job);tx.put('agiso_orders',link)
        return {'ok':True}

    def replayable(event,shop):
        return bool(shop['enabled'] and event['status']=='manual' and event.get('error') in {'unmapped_sku','conflicting_rules','quota_exceeded'})

    @app.get('/api/agiso/shops/{id}/events')
    def events(id:str,request:Request):
        with db.transaction() as tx:
            actor,shop=scoped(tx,request,id)
            return [{k:e.get(k) for k in ('id','topic','status','error','received_at','order_number')} | {'can_replay':can_manage(actor,shop) and replayable(e,shop)}
                    for e in reversed(tx.all('agiso_events')) if e['shop_id']==id]

    @app.post('/api/agiso/shops/{id}/events/{event_id}/replay')
    def replay(id:str,event_id:str,request:Request):
        with db.transaction() as tx:
            _,shop=scoped(tx,request,id,True);event=tx.get('agiso_events',event_id)
            if not event or event['shop_id']!=id:raise HTTPException(404,'记录不存在')
            link=tx.get('agiso_orders',integration_id(id,event['payload']['Tid'])) if event['topic']=='1' else None
            if not replayable(event,shop) or not executable(tx,shop,now()) or link and (link.get('customer_order_id') or link.get('holds') or link['open_status']=='cancelled'):raise HTTPException(409,'当前事件不能重放')
            event.update(status='pending',error=None);tx.put('agiso_events',event)
        return {'ok':True}

    @app.post('/api/agiso/webhook')
    async def webhook(request:Request):
        body=bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body)>protocol.MAX_BODY:raise HTTPException(413,'通知过大')
        config=require_config()
        query=request.query_params
        if any(len(query.getlist(k))!=1 for k in ('timestamp','sign','aopic','fromPlatform')):raise HTTPException(422,'通知参数无效')
        if query['fromPlatform']!='PddAlds':raise HTTPException(422,'通知平台无效')
        if request.headers.get('content-type','').split(';')[0].lower()!='application/x-www-form-urlencoded':raise HTTPException(422,'通知格式无效')
        try:
            fields=parse_qs(body.decode('utf-8'),strict_parsing=True,max_num_fields=2)
            if set(fields)!={'json'} or len(fields['json'])!=1:raise ValueError()
            raw=fields['json'][0]
            if not query['timestamp'].isdigit() or len(query['timestamp'])>16:raise ValueError()
        except (ValueError,UnicodeError):raise HTTPException(422,'通知格式无效')
        expected=protocol.sign(config['secret'],{'json':raw,'timestamp':query['timestamp']})
        supplied=query['sign'].lower()
        if len(supplied)!=32 or not hmac.compare_digest(expected,supplied):raise HTTPException(403,'通知签名无效')
        try:
            def unique_pairs(pairs):
                result={}
                for key,value in pairs:
                    if key in result:raise ValueError()
                    result[key]=value
                return result
            payload=json.loads(raw,object_pairs_hook=unique_pairs)
            if not isinstance(payload,dict):raise ValueError()
            topic=query['aopic']
            if topic=='1':
                if {'refund_id','operation','mall_id'} & payload.keys():raise ValueError()
                payload=protocol.Trade.model_validate(payload).model_dump();mall=payload['MallId'];number=payload['OrderSn']
            elif topic in {'8','16','32'}:
                if {'ItemList','MallId','ConfirmTime'} & payload.keys():raise ValueError()
                payload=protocol.Refund.model_validate(payload).model_dump();mall=payload['mall_id'];number=payload['tid']
            else:raise ValueError()
        except (ValueError,ValidationError,TypeError):raise HTTPException(422,'通知内容无效')
        # Topic is not signed; derive identity from the validated signed payload and family.
        event_id=token_hash(('trade:' if topic=='1' else 'refund:')+json.dumps(payload,sort_keys=True,ensure_ascii=False))
        with db.transaction() as tx:
            if not tx.get('agiso_events',event_id):
                shop=next((s for s in tx.all('agiso_shops') if s['shop_id']==mall),None)
                tx.put('agiso_events',{'id':event_id,'shop_id':shop['id'] if shop else '', 'topic':topic,'payload':payload,
                       'order_number':number,'status':'pending' if shop and (shop['enabled'] or topic!='1') else 'disabled','error':None if shop and (shop['enabled'] or topic!='1') else 'shop_disabled',
                       'received_at':now(),'lease_until':0})
                if shop:shop['last_event_at']=now();tx.put('agiso_shops',shop)
        return Response(status_code=200,content=b'')
