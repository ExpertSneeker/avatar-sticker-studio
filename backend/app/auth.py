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
    from .credits import wallet
    return {key: user[key] for key in ('id', 'username', 'display_name', 'role', 'watermark', 'print_defaults')} | {'credits':wallet(user), 'generation_concurrency':generation_limit(user), 'can_edit_library':can_edit_library(user)}


def require_user(tx, token, now):
    session = tx.get('sessions', token_hash(token or ''))
    user = tx.get('users', session['user_id']) if session and session['expires'] > now else None
    if not user or not user['active']:
        raise HTTPException(401, '请先登录')
    return user


def require_admin(user):
    if user['role'] != 'admin':
        raise HTTPException(403, '需要管理员权限')


def owned(tx, kind, id, user):
    value = tx.get(kind, id)
    if not value or (value.get('owner') != user['id'] and user['role'] != 'admin'):
        raise HTTPException(404, '记录不存在')
    return value


def can_read_asset(asset, actor):
    return bool(asset and (actor['role']=='admin' or asset.get('owner')==actor['id'] or
                asset['kind']=='template' and asset.get('scope','public')=='public'))


def can_use_template(template, actor):
    return bool(template and template['active'] and not template.get('deleted') and
                (template.get('scope','public')=='public' or template.get('owner')==actor['id']))


def can_edit_library(actor):
    return actor['role']=='admin' or actor.get('can_edit_library', False) is True


def require_library_editor(actor):
    if not can_edit_library(actor):
        raise HTTPException(403, '需要公共图库编辑权限')


def can_edit_template(template, actor):
    return can_edit_library(actor)
