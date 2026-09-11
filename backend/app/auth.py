import hashlib
import hmac
import secrets
from fastapi import HTTPException

DEFAULT_GENERATION_CONCURRENCY = 2


def generation_limit(user):
    return user.get('generation_concurrency', DEFAULT_GENERATION_CONCURRENCY)


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest


def verify_password(password, encoded):
    salt, expected = encoded.split(':')
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(digest, expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user):
    return {key: user[key] for key in ('id', 'username', 'display_name', 'role', 'watermark', 'print_defaults')} | {'organization_id':user.get('organization_id'), 'organization_name':user.get('organization_name'), 'generation_concurrency':generation_limit(user), 'can_edit_library':can_edit_library(user)}


def require_user(tx, token, now):
    session = tx.get('sessions', token_hash(token or ''))
    user = tx.get('users', session['user_id']) if session and session['expires'] > now else None
    organization = tx.get('organizations', user.get('organization_id','')) if user else None
    if not user or not user['active'] or (user.get('role') != 'superadmin' and (not organization or not organization.get('active'))):
        raise HTTPException(401, '请先登录')
    return user


def require_admin(user):
    if user['role'] not in {'superadmin', 'org_admin'}:
        raise HTTPException(403, '需要管理员权限')


def require_superadmin(user):
    if user['role'] != 'superadmin':
        raise HTTPException(403, '需要超级管理员权限')


def same_organization(value, actor):
    return bool(value and actor.get('organization_id') and value.get('organization_id') == actor['organization_id'])


def owned(tx, kind, id, user):
    value = tx.get(kind, id)
    if not value or (user['role'] != 'superadmin' and not same_organization(value, user)):
        raise HTTPException(404, '记录不存在')
    return value


def managed_user(tx, id, actor):
    require_admin(actor)
    value = tx.get('users', id)
    if not value or (actor['role'] != 'superadmin' and (not same_organization(value, actor) or value['role'] == 'superadmin')):
        raise HTTPException(404, '账号不存在')
    return value


def can_read_asset(asset, actor):
    return bool(asset and (actor['role'] == 'superadmin' or same_organization(asset, actor)))


def can_use_template(template, actor):
    return bool(template and template['active'] and not template.get('deleted') and same_organization(template, actor))


def can_edit_library(actor):
    return actor['role'] in {'superadmin', 'org_admin'} or actor.get('can_edit_library', False) is True


def require_library_editor(actor):
    if not can_edit_library(actor):
        raise HTTPException(403, '需要公共图库编辑权限')


def can_edit_template(template, actor):
    return same_organization(template, actor) and can_edit_library(actor)
