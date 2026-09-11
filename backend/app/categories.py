"""Shared editable category identities; catalog edits never rewrite order history."""
from fastapi import HTTPException, Request
from .auth import same_organization, require_library_editor
from .db import uid
from .schemas import CategoryWrite

DEFAULT_CATEGORIES = {'boy':'男孩','girl':'女孩','animal':'动物','general':'通用'}


def seed_categories(tx):
    if tx.get('migrations','library-categories-v1'):
        return
    for id, name in DEFAULT_CATEGORIES.items():
        tx.put('library_categories', {'id':id,'name':name})
    tx.put('migrations', {'id':'library-categories-v1'})


def resolve_category(tx, value, actor=None):
    value = next((id for id,name in DEFAULT_CATEGORIES.items() if name==value),value)
    category=tx.get('library_categories',value)
    if actor is not None and not same_organization(category,actor):
        category=next((c for c in tx.all('library_categories') if same_organization(c,actor) and c.get('key')==value),None)
    if not category:
        raise HTTPException(422,'分类不存在或已删除，请重新选择')
    return category['id']


def register_categories(app, db, user):
    @app.get('/api/library/categories')
    def categories(request: Request):
        with db.transaction() as tx:
            actor=user(tx,request)
            return [c for c in tx.all('library_categories') if same_organization(c,actor)]

    def write(data, request, id=None):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            if id and not same_organization(tx.get('library_categories',id),actor):
                raise HTTPException(404,'分类不存在')
            if any(same_organization(c,actor) and c['id']!=id and c['name'].casefold()==data.name.casefold() for c in tx.all('library_categories')):
                raise HTTPException(409,'分类名称已存在')
            return tx.put('library_categories',{**(tx.get('library_categories',id) if id else {}),'id':id or uid(),'name':data.name,'organization_id':actor['organization_id']})

    @app.post('/api/library/categories')
    def create(data: CategoryWrite, request: Request):
        return write(data,request)

    @app.patch('/api/library/categories/{id}')
    def edit(id: str, data: CategoryWrite, request: Request):
        return write(data,request,id)

    @app.delete('/api/library/categories/{id}')
    def delete(id: str, request: Request):
        with db.transaction() as tx:
            actor=user(tx,request);require_library_editor(actor)
            if not same_organization(tx.get('library_categories',id),actor):
                raise HTTPException(404,'分类不存在')
            if id=='general' or tx.get('library_categories',id).get('key')=='general':
                raise HTTPException(409,'默认分类可重命名，但不能删除')
            refs=[{'id':r['id'],'code':r['code'],'name':r['name'],'kind':kind}
                  for kind in ('stickers','templates') for r in tx.all(kind)
                  if same_organization(r,actor) and not r.get('deleted') and (r['category']==id or r['category']==DEFAULT_CATEGORIES.get(id))]
            if refs:
                raise HTTPException(409,{'message':'分类仍被以下资源使用，请先修改这些资源的分类。','resources':refs})
            tx.delete('library_categories',id)
            return {'id':id,'deleted':True}
