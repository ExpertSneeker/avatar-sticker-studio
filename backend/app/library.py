"""Shared sticker library and immutable, source-traceable revisions."""
import json
from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile
from .auth import same_organization, managed_user, can_edit_library, require_library_editor, require_admin, public_user
from .db import uid
from .schemas import ActivePatch, LibraryPermissionPatch, TemplateWrite, StickerBatch, safe_name
from .storage import normalize_image, save_asset

CATEGORIES = {'男孩':'boy', '女孩':'girl', '动物':'animal', '通用':'general'}


def snapshot(tx, kind, value):
    tx.put(kind[:-1] + '_revisions', {**value, 'id':value['id']+':'+str(value['revision']), kind[:-1]+'_id':value['id']})


def hydrate_template(tx, value):
    result = {**value, 'category':CATEGORIES.get(value['category'],value['category'])}
    if 'sticker_ids' in value:
        images=[]
        for position, id in enumerate(value['sticker_ids'],1):
            sticker=tx.get('stickers',id)
            if not sticker:
                images.append({'sticker_id':id,'position':position,'active':False})
            else:
                images.append({**sticker['image'],'position':position,'sticker_id':id,'code':sticker['code'],'revision':sticker['revision'],'active':sticker['active']})
        result['images']=images
    result['available']=bool(value.get('active') and not value.get('deleted') and result.get('images') and all(i.get('active',True) for i in result['images']))
    return result


def migrate_library(tx):
    if tx.get('migrations','public-stickers-v1'):
        return
    used={s['code'].casefold() for s in tx.all('stickers')}
    by_asset={s['image']['id']:s['id'] for s in tx.all('stickers')}
    created_sticker_ids=set()
    for template in tx.all('templates'):
        ids=[]
        for position,image in enumerate(template['images'],1):
            asset_id=image['id']
            if asset_id not in by_asset:
                base=f"{template['code'][:96]}-{position:02}"
                code=base
                if code.casefold() in used or code=='拼版':
                    code=f'{base[:91]}-{asset_id[:8]}'
                suffix=2
                while code.casefold() in used:
                    ending=f'-{asset_id[:8]}-{suffix}'
                    code=base[:100-len(ending)]+ending;suffix+=1
                used.add(code.casefold())
                sticker={'id':uid(),'organization_id':template.get('organization_id'),'code':code,'name':template['name'],'category':CATEGORIES.get(template['category'],template['category']),'active':True,'revision':1,'image':{'id':asset_id,'url':image['url']}}
                tx.put('stickers',sticker);snapshot(tx,'stickers',sticker)
                by_asset[asset_id]=sticker['id']
                created_sticker_ids.add(sticker['id'])
            ids.append(by_asset[asset_id])
        template.update(scope='public',owner=None,sticker_ids=ids)
        tx.put('templates',template)
    for asset in tx.all('assets'):
        if asset['kind']=='template':
            asset.update(scope='public',owner=None);tx.put('assets',asset)
    for actor in tx.all('users'):
        actor['can_edit_library']=actor['role'] in {'admin','org_admin','superadmin'}
        tx.put('users',actor)
    derived={t['id']:[sid for sid in t.get('sticker_ids',[]) if sid in created_sticker_ids] for t in tx.all('templates')}
    tx.put('migrations',{'id':'public-stickers-v1','derived_sticker_ids_by_template':derived})


def register_library(app, db, user):
    from .categories import register_categories, resolve_category
    register_categories(app, db, user)
    def sticker_public(value,actor):
        return {**value,'editable':can_edit_library(actor)}

    def template_public(tx,value,actor):
        return {**hydrate_template(tx,value),'scope':'public','owner':None,'editable':can_edit_library(actor)}

    @app.patch('/api/admin/users/{id}/library-permission')
    def permission(id: str, data: LibraryPermissionPatch, request: Request):
        with db.transaction() as tx:
            actor=user(tx,request);require_admin(actor)
            target=managed_user(tx,id,actor)
            if not target: raise HTTPException(404,'用户不存在')
            target['can_edit_library']=data.can_edit_library if target['role'] not in {'org_admin','superadmin'} else True
            tx.put('users',target)
            return {**public_user(target),'active':target['active']}

    @app.get('/api/stickers')
    def stickers(request: Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            return [sticker_public(s,actor) for s in tx.all('stickers') if same_organization(s,actor) and not s.get('deleted') and (s['active'] or can_edit_library(actor))]

    async def write_stickers(request,id=None):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
        async with request.form(max_files=100,max_fields=10,max_part_size=25*1024*1024) as form:
            files=form.getlist('files') or form.getlist('files[]') or form.getlist('file')
            if (id and len(files)>1) or (not id and not 1<=len(files)<=100):
                raise HTTPException(422,'请选择1至100张贴纸图片')
            for file in files:
                if not isinstance(file,UploadFile): raise HTTPException(422,'图片上传无效')
                data=await file.read(25*1024*1024+1)
                if len(data)>25*1024*1024: raise HTTPException(413,'单张图片不得超过25MB')
                normalized=normalize_image(data)
                await file.seek(0)
                await file.write(normalized)
                file.file.truncate()
                await file.seek(0)
                del data, normalized
            saved_paths=[]
            try:
                with db.transaction() as tx:
                    actor=user(tx,request);require_library_editor(actor)
                    old=tx.get('stickers',id) if id else None
                    if id and (not same_organization(old,actor) or old.get('deleted')): raise HTTPException(404,'贴纸不存在')
                    try:
                        if id:
                            codes=[safe_name(str(form.get('code',old['code'])))]
                        else:
                            codes=json.loads(str(form['codes'])) if 'codes' in form else [safe_name(file.filename.rsplit('.',1)[0]) for file in files]
                            if not isinstance(codes,list) or len(codes)!=len(files) or any(not isinstance(c,str) for c in codes): raise ValueError('编号数量须与图片数量一致')
                            codes=[safe_name(c) for c in codes]
                        if '拼版' in codes: raise ValueError('贴纸编号“拼版”为导出拼版文件保留，请使用其他编号')
                        name=safe_name(str(form.get('name',old['name'] if old else codes[0])))
                        cat=resolve_category(tx,str(form.get('category',old['category'] if old else 'general')),actor)
                    except (TypeError,ValueError) as exc:
                        raise HTTPException(422,str(exc)) from exc
                    existing={s['code'].casefold() for s in tx.all('stickers') if same_organization(s,actor) and s['id']!=id and not s.get('deleted')}
                    folded=[c.casefold() for c in codes]
                    if len(set(folded))!=len(folded) or existing.intersection(folded): raise HTTPException(409,'贴纸编号已存在')
                    values=[]
                    for index,code in enumerate(codes):
                        image=old['image'] if old else None
                        if files:
                            asset=save_asset(db,tx,files[index].file.read(),None,'template',organization_id=actor['organization_id'])
                            saved_paths.append(db.root/'assets'/asset['file'])
                            asset['scope']='public';tx.put('assets',asset)
                            image={'id':asset['id'],'url':asset['url']}
                        value={'id':id or uid(),'organization_id':actor['organization_id'],'code':code,'name':name if 'name' in form or old else code,'category':cat,'active':True,'revision':old['revision']+1 if old else 1,'image':image}
                        tx.put('stickers',value);snapshot(tx,'stickers',value);values.append(value)
                    return sticker_public(values[0],user(tx,request)) if id else [sticker_public(value,user(tx,request)) for value in values]
            except BaseException:
                for path in saved_paths:
                    path.unlink(missing_ok=True)
                raise

    @app.post('/api/stickers')
    async def create_stickers(request: Request): return await write_stickers(request)

    @app.put('/api/stickers/{id}')
    async def edit_sticker(id: str,request: Request): return await write_stickers(request,id)

    @app.patch('/api/stickers/{id}')
    def retired_sticker_status(id: str,data: ActivePatch,request: Request):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            raise HTTPException(410,'贴纸和模板已取消停用功能，请刷新页面；需要移除资源时请使用删除。')

    @app.get('/api/templates')
    def templates(request: Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            return [template_public(tx,t,actor) for t in tx.all('templates') if same_organization(t,actor) and not t.get('deleted') and (t['active'] or can_edit_library(actor))]

    def write_template(data,request,id=None):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            old=tx.get('templates',id) if id else None
            if id and (not same_organization(old,actor) or old.get('deleted')): raise HTTPException(404,'套装不存在')
            if any(same_organization(t,actor) and t['code'].casefold()==data.code.casefold() and t['id']!=id and not t.get('deleted') for t in tx.all('templates')): raise HTTPException(409,'套装编号已存在')
            if any(not same_organization((s:=tx.get('stickers',sid)),actor) or not s['active'] or s.get('deleted') for sid in data.sticker_ids): raise HTTPException(422,'套装包含不存在或不可用的贴纸')
            value={**data.model_dump(),'organization_id':actor['organization_id'],'category':resolve_category(tx,data.category,actor),'id':id or uid(),'scope':'public','owner':None,'active':True,'revision':old['revision']+1 if old else 1}
            value=hydrate_template(tx,value)
            tx.put('templates',value);snapshot(tx,'templates',value)
            return template_public(tx,value,actor)

    @app.post('/api/templates')
    def create_template(data: TemplateWrite,request: Request): return write_template(data,request)

    @app.put('/api/templates/{id}')
    def edit_template(id: str,data: TemplateWrite,request: Request): return write_template(data,request,id)

    @app.patch('/api/templates/{id}')
    def retired_template_status(id: str,data: ActivePatch,request: Request):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            raise HTTPException(410,'贴纸和模板已取消停用功能，请刷新页面；需要移除资源时请使用删除。')

    def delete_entry(kind, id, request):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            value = tx.get(kind, id)
            if not same_organization(value,actor):
                raise HTTPException(404, '贴纸不存在' if kind == 'stickers' else '模板不存在')
            if value.get('deleted'):
                return {'id': id, 'deleted': True}
            if kind == 'stickers':
                references = [{k: t[k] for k in ('id', 'code', 'name', 'active')}
                              for t in tx.all('templates')
                              if not t.get('deleted') and id in t.get('sticker_ids', [])]
                if references:
                    raise HTTPException(409, {'message': '贴纸仍被模板使用，请先从以下模板中移除此贴纸或删除模板。',
                                              'templates': references})
            # Keep source assets and immutable revisions for submitted orders.
            value.update(deleted=True, active=False, revision=value['revision'] + 1)
            if kind == 'templates':
                value['available'] = False
            tx.put(kind, value)
            snapshot(tx, kind, value)
            return {'id': id, 'deleted': True}

    @app.delete('/api/templates/{id}')
    def delete_template(id: str, request: Request):
        return delete_entry('templates', id, request)

    @app.delete('/api/stickers/{id}')
    def delete_sticker(id: str, request: Request):
        return delete_entry('stickers', id, request)

    @app.post('/api/stickers/batch')
    def batch(data: StickerBatch, request: Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            require_library_editor(actor)
            values=[tx.get('stickers',id) for id in data.ids]
            if any(not same_organization(s,actor) or s.get('deleted') for s in values):
                raise HTTPException(404,'所选贴纸已被删除，请刷新后重试')
            if data.action=='delete':
                references=[]
                templates=tx.all('templates')
                for s in values:
                    refs=[{k:t[k] for k in ('id','code','name','active')} for t in templates
                          if not t.get('deleted') and s['id'] in t.get('sticker_ids',[])]
                    if refs:
                        references.append({'sticker':{'id':s['id'],'code':s['code']},'templates':refs})
                if references:
                    raise HTTPException(409,{'message':'部分贴纸仍被模板使用，本次未删除任何贴纸。','references':references})
                changes={'deleted':True,'active':False}
            else:
                changes={}
                if data.category is not None:
                    changes['category']=resolve_category(tx,data.category,actor)
            for s in values:
                if any(s.get(k)!=v for k,v in changes.items()):
                    s.update(changes)
                    s['revision']+=1
                    tx.put('stickers',s)
                    snapshot(tx,'stickers',s)
            return {'count':len(values)}


def migrate_library_status(tx):
    if tx.get('migrations','library-always-available-v1'):
        return
    # Deleted catalog entries and historical revisions must remain untouched.
    for kind in ('stickers','templates'):
        for value in tx.all(kind):
            if not value.get('deleted') and not value.get('active'):
                value.update(active=True,revision=value['revision']+1)
                if kind=='templates':
                    value=hydrate_template(tx,value)
                tx.put(kind,value)
                snapshot(tx,kind,value)
    tx.put('migrations',{'id':'library-always-available-v1'})
