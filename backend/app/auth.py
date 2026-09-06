import hashlib
import hmac
import secrets
from fastapi import HTTPException


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
    return {key: user[key] for key in ('id', 'username', 'display_name', 'role', 'watermark', 'print_defaults')}


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
