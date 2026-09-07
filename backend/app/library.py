"""Shared sticker library and immutable, source-traceable revisions."""
import json
from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile
from .auth import can_edit_library, require_library_editor, require_admin, public_user
from .db import uid
from .schemas import ActivePatch, LibraryPermissionPatch, TemplateWrite, safe_name
from .storage import normalize_image, save_asset

CATEGORIES = {'男孩':'boy', '女孩':'girl', '动物':'animal', '通用':'general'}


def category(value):
    value = CATEGORIES.get(value, value)
    if value not in {'boy','girl','animal','general'}:
        raise ValueError('分类必须为男孩、女孩、动物或通用')
    return value


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
                sticker={'id':uid(),'code':code,'name':template['name'],'category':CATEGORIES.get(template['category'],template['category']),'active':True,'revision':1,'image':{'id':asset_id,'url':image['url']}}
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
        actor['can_edit_library']=actor['role']=='admin'
        tx.put('users',actor)
    derived={t['id']:[sid for sid in t.get('sticker_ids',[]) if sid in created_sticker_ids] for t in tx.all('templates')}
    tx.put('migrations',{'id':'public-stickers-v1','derived_sticker_ids_by_template':derived})


def register_library(app, db, user):
    def sticker_public(value,actor):
        return {**value,'editable':can_edit_library(actor)}

    def template_public(tx,value,actor):
        return {**hydrate_template(tx,value),'scope':'public','owner':None,'editable':can_edit_library(actor)}

    @app.patch('/api/admin/users/{id}/library-permission')
    def permission(id: str, data: LibraryPermissionPatch, request: Request):
        with db.transaction() as tx:
            require_admin(user(tx,request))
            target=tx.get('users',id)
            if not target: raise HTTPException(404,'用户不存在')
            target['can_edit_library']=data.can_edit_library if target['role']!='admin' else True
            tx.put('users',target)
            return {**public_user(target),'active':target['active']}

    @app.get('/api/stickers')
    def stickers(request: Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            return [sticker_public(s,actor) for s in tx.all('stickers') if not s.get('deleted') and (s['active'] or can_edit_library(actor))]

    async def write_stickers(request,id=None):
        with db.transaction() as tx:
            require_library_editor(user(tx,request))
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
                    require_library_editor(user(tx,request))
                    old=tx.get('stickers',id) if id else None
                    if id and (not old or old.get('deleted')): raise HTTPException(404,'贴纸不存在')
                    try:
                        if id:
                            codes=[safe_name(str(form.get('code',old['code'])))]
                        else:
                            codes=json.loads(str(form['codes'])) if 'codes' in form else [safe_name(file.filename.rsplit('.',1)[0]) for file in files]
                            if not isinstance(codes,list) or len(codes)!=len(files) or any(not isinstance(c,str) for c in codes): raise ValueError('编号数量须与图片数量一致')
                            codes=[safe_name(c) for c in codes]
                        if '拼版' in codes: raise ValueError('贴纸编号“拼版”为导出拼版文件保留，请使用其他编号')
                        name=safe_name(str(form.get('name',old['name'] if old else codes[0])))
                        cat=category(str(form.get('category',old['category'] if old else 'general')))
                    except (TypeError,ValueError) as exc:
                        raise HTTPException(422,str(exc)) from exc
                    existing={s['code'].casefold() for s in tx.all('stickers') if s['id']!=id}
                    folded=[c.casefold() for c in codes]
                    if len(set(folded))!=len(folded) or existing.intersection(folded): raise HTTPException(409,'贴纸编号已存在')
                    values=[]
                    for index,code in enumerate(codes):
                        image=old['image'] if old else None
                        if files:
                            asset=save_asset(db,tx,files[index].file.read(),None,'template')
                            saved_paths.append(db.root/'assets'/asset['file'])
                            asset['scope']='public';tx.put('assets',asset)
                            image={'id':asset['id'],'url':asset['url']}
                        value={'id':id or uid(),'code':code,'name':name if 'name' in form or old else code,'category':cat,'active':old['active'] if old else True,'revision':old['revision']+1 if old else 1,'image':image}
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
    def toggle_sticker(id: str,data: ActivePatch,request: Request):
        with db.transaction() as tx:
            require_library_editor(user(tx,request))
            value=tx.get('stickers',id)
            if not value or value.get('deleted'): raise HTTPException(404,'贴纸不存在')
            if value['active']!=data.active:
                value.update(active=data.active,revision=value['revision']+1)
                tx.put('stickers',value);snapshot(tx,'stickers',value)
            return sticker_public(value,user(tx,request))

    @app.get('/api/templates')
    def templates(request: Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            return [template_public(tx,t,actor) for t in tx.all('templates') if not t.get('deleted') and (t['active'] or can_edit_library(actor))]

    def write_template(data,request,id=None):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            old=tx.get('templates',id) if id else None
            if id and (not old or old.get('deleted')): raise HTTPException(404,'套装不存在')
            if any(t['code'].casefold()==data.code.casefold() and t['id']!=id and not t.get('deleted') for t in tx.all('templates')): raise HTTPException(409,'套装编号已存在')
            if any(not (s:=tx.get('stickers',sid)) or not s['active'] or s.get('deleted') for sid in data.sticker_ids): raise HTTPException(422,'套装包含不存在或已停用的贴纸')
            value={**data.model_dump(),'id':id or uid(),'scope':'public','owner':None,'active':old['active'] if old else True,'revision':old['revision']+1 if old else 1}
            value=hydrate_template(tx,value)
            tx.put('templates',value);snapshot(tx,'templates',value)
            return template_public(tx,value,actor)

    @app.post('/api/templates')
    def create_template(data: TemplateWrite,request: Request): return write_template(data,request)

    @app.put('/api/templates/{id}')
    def edit_template(id: str,data: TemplateWrite,request: Request): return write_template(data,request,id)

    @app.patch('/api/templates/{id}')
    def toggle_template(id: str,data: ActivePatch,request: Request):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            value=tx.get('templates',id)
            if not value or value.get('deleted'): raise HTTPException(404,'套装不存在')
            if value['active']!=data.active:
                value.update(active=data.active,revision=value['revision']+1)
                value=hydrate_template(tx,value)
                tx.put('templates',value);snapshot(tx,'templates',value)
            return template_public(tx,value,actor)
