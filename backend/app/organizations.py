"""Organization provisioning and one-time legacy tenancy migration."""
import secrets
import time
from fastapi import HTTPException, Request
from .auth import public_user, require_superadmin
from .db import uid
from .schemas import OrganizationCreate, OrganizationPatch


def create_organization(tx, name, initial=False):
    name = name.strip()
    if any(o['name'].casefold() == name.casefold() for o in tx.all('organizations')):
        raise HTTPException(409, '组织名称已存在')
    org = tx.put('organizations', {'id':uid(), 'name':name, 'active':True})
    from .categories import DEFAULT_CATEGORIES
    for key, label in DEFAULT_CATEGORIES.items():
        id = key if initial else org['id'] + ':' + key
        category = tx.get('library_categories',id) if initial else None
        tx.put('library_categories', {**(category or {'id':id,'name':label,'key':key}),'organization_id':org['id']})
    return org


def migrate_organizations(tx):
    if tx.get('migrations', 'organizations-v1'):
        return
    existing = tx.all('organizations')
    org = existing[0] if existing else create_organization(tx, '默认组织', initial=True)
    for user in tx.all('users'):
        user.setdefault('organization_id', org['id'])
        user['organization_name'] = (tx.get('organizations', user['organization_id']) or org)['name']
        if user.get('role') == 'admin' or user.get('username','').casefold() == 'magnus':
            user['role'] = 'org_admin'
        tx.put('users', user)
    for kind in ('orders','items','uploads','assets','templates','template_revisions','stickers','sticker_revisions','library_categories','invites','generations'):
        for value in tx.all(kind):
            owner = tx.get('users', value.get('owner',''))
            if not value.get('organization_id'):
                value['organization_id'] = owner.get('organization_id') if owner else org['id']
            tx.put(kind, value)
    # Only a positively known terminal request may release historical holds.
    from .credits import settle, wallet
    for generation in tx.all('generations'):
        item = tx.get('items', generation.get('item_id',''))
        owner = tx.get('users', generation.get('owner',''))
        if owner and wallet(owner)['frozen'] > 0 and generation.get('status') in {'reserved','review'} and item and item.get('status') in {'completed','failed'} and not item.get('remote_reserved') and not item.get('cutout_inflight'):
            settle(tx, generation['id'], 'release', time.time(), reason='取消积分制：释放已结束请求的历史冻结')
    tx.put('migrations', {'id':'organizations-v1','default_organization_id':org['id']})


def register_organizations(app, db, user, register_user):
    @app.get('/api/admin/organizations')
    def organizations(request: Request):
        with db.transaction() as tx:
            require_superadmin(user(tx,request))
            return tx.all('organizations')

    @app.post('/api/admin/organizations')
    def create(data: OrganizationCreate, request: Request):
        with db.transaction() as tx:
            require_superadmin(user(tx,request))
            org = create_organization(tx,data.name)
            temporary = secrets.token_urlsafe(24)
            from .schemas import Signup
            actor = register_user(tx, Signup(username=data.admin_username,display_name=data.admin_display_name,password=temporary), 'org_admin', org['id'])
            return {'organization':org,'admin':public_user(actor),'temporary_password':temporary}

    @app.patch('/api/admin/organizations/{id}')
    def update(id: str, data: OrganizationPatch, request: Request):
        with db.transaction() as tx:
            require_superadmin(user(tx,request))
            org=tx.get('organizations',id)
            if not org: raise HTTPException(404,'组织不存在')
            if data.name is not None and any(o['id']!=id and o['name'].casefold()==data.name.casefold() for o in tx.all('organizations')):
                raise HTTPException(409,'组织名称已存在')
            org.update(data.model_dump(exclude_none=True));tx.put('organizations',org)
            for member in tx.all('users'):
                if member.get('organization_id')==id:
                    member['organization_name']=org['name'];tx.put('users',member)
            return org
