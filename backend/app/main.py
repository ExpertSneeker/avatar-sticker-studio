"""Private local Avatar Sticker Studio HTTP API."""
import hashlib
import io
import json
import os
import secrets
import time
import unicodedata
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from .auth import hash_password, owned, public_user, require_admin, require_user, token_hash, verify_password
from .db import Database, uid
from .schemas import AccountPatch, ActivePatch, Credentials, OrderCreate, PasswordChange, PrintSettings, Repack, ResolveUnknown, SettingsPatch, Signup, UploadInit, safe_name
from .storage import asset_bytes, normalize_image, save_asset


def create_app(data_root=None, provider=None, clock=None, start_worker=True):
    db = Database(data_root or os.environ.get('STUDIO_DATA_DIR', '.data'))
    now = clock or time.time

    @asynccontextmanager
    async def lifespan(app):
        from .worker import Worker
        app.state.worker = Worker(db, provider=provider, clock=now)
        if start_worker:
            await app.state.worker.start()
        yield
        if start_worker:
            await app.state.worker.stop()

    app = FastAPI(title='Avatar Sticker Studio', lifespan=lifespan)
    app.state.db, app.state.clock = db, now

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = '; '.join('.'.join(str(x) for x in e['loc'][1:]) + ': ' + e['msg'] for e in exc.errors())
        return JSONResponse({'detail': errors}, status_code=422)

    @app.middleware('http')
    async def protect_origin(request, call_next):
        allowed_hosts = set(os.environ.get('STUDIO_ALLOWED_HOSTS', 'localhost,127.0.0.1,::1,testserver').split(','))
        if request.url.hostname not in allowed_hosts:
            return JSONResponse({'detail': '请求主机名不受信任'}, status_code=400)
        origin = request.headers.get('origin')
        if request.method not in {'GET', 'HEAD', 'OPTIONS'} and origin:
            allowed = set(os.environ.get('STUDIO_ALLOWED_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000').split(','))
            allowed.add(str(request.base_url).rstrip('/'))
            if origin not in allowed:
                return JSONResponse({'detail': '请求来源不受信任'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def user(tx, request):
        actor = require_user(tx, request.cookies.get('studio_session'), now())
        expected = request.headers.get('X-Studio-User')
        if expected is not None and expected != actor['id']:
            raise HTTPException(401, '登录账号已变化，请重新登录')
        return actor

    def admin(tx, request):
        value = user(tx, request)
        require_admin(value)
        return value

    def session(tx, response, value):
        token = secrets.token_urlsafe(32)
        tx.put('sessions', {'id': token_hash(token), 'user_id': value['id'], 'expires': now() + 7 * 86400})
        response.set_cookie('studio_session', token, max_age=7 * 86400, httponly=True, samesite='strict', secure=os.environ.get('STUDIO_SECURE_COOKIE') == '1', path='/')
        return public_user(value)

    def register_user(tx, data, role):
        if any(u['username'].casefold() == data.username.casefold() for u in tx.all('users')):
            raise HTTPException(409, '用户名已存在')
        value = {'id': uid(), 'username': data.username, 'password': hash_password(data.password), 'display_name': data.display_name.strip(), 'role': role, 'watermark': '', 'print_defaults': PrintSettings().model_dump(), 'active': True}
        tx.put('users', value)
        return value

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/auth/status')
    def auth_status(request: Request):
        with db.transaction() as tx:
            try:
                value = public_user(user(tx, request))
            except HTTPException:
                value = None
            return {'needs_setup': not tx.all('users'), 'user': value}

    @app.post('/api/auth/setup')
    def setup(data: Signup, response: Response, request: Request):
        if request.client and request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
            raise HTTPException(403, '首次管理员设置仅允许本机访问')
        with db.transaction() as tx:
            if tx.all('users'):
                raise HTTPException(409, '管理员已设置，请登录或使用邀请码')
            return session(tx, response, register_user(tx, data, 'admin'))

    @app.post('/api/auth/register')
    def register(data: Signup, response: Response):
        with db.transaction() as tx:
            invite = tx.get('invites', token_hash(data.invite or ''))
            if not invite or invite['used'] or invite['expires'] < now():
                raise HTTPException(400, '邀请码无效、已使用或已过期')
            value = register_user(tx, data, 'staff')
            invite['used'] = True
            tx.put('invites', invite)
            return session(tx, response, value)

    @app.post('/api/auth/login')
    def login(data: Credentials, response: Response, request: Request):
        with db.transaction() as tx:
            key = token_hash((request.client.host if request.client else '') + ':' + data.username.casefold())
            attempts = tx.get('login_limits', key) or {'id': key, 'times': []}
            attempts['times'] = [t for t in attempts['times'] if t > now() - 900]
            if len(attempts['times']) >= 12:
                raise HTTPException(429, '登录尝试过多，请15分钟后重试')
            value = next((u for u in tx.all('users') if u['username'].casefold() == data.username.casefold()), None)
            valid = value and verify_password(data.password, value['password']) and value['active']
            if valid:
                tx.delete('login_limits', key)
                return session(tx, response, value)
            attempts['times'].append(now())
            tx.put('login_limits', attempts)
        raise HTTPException(401, '用户名或密码错误，或账号已停用')

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        with db.transaction() as tx:
            if request.headers.get('X-Studio-User') is not None:
                user(tx, request)
            tx.delete('sessions', token_hash(request.cookies.get('studio_session', '')))
        response.delete_cookie('studio_session', path='/')
        return {'ok': True}

    @app.get('/api/auth/me')
    def me(request: Request):
        with db.transaction() as tx:
            return public_user(user(tx, request))

    @app.patch('/api/account')
    def account(data: AccountPatch, request: Request):
        with db.transaction() as tx:
            value = user(tx, request)
            value.update(data.model_dump(exclude_none=True))
            tx.put('users', value)
            return public_user(value)

    @app.post('/api/account/password')
    def password(data: PasswordChange, request: Request, response: Response):
        with db.transaction() as tx:
            value = user(tx, request)
            if not verify_password(data.current_password, value['password']):
                raise HTTPException(400, '当前密码错误')
            value['password'] = hash_password(data.new_password)
            tx.put('users', value)
            for s in tx.all('sessions'):
                if s['user_id'] == value['id']:
                    tx.delete('sessions', s['id'])
            session(tx, response, value)
            return {'ok': True}

    def public_settings(config):
        return {**{k: config[k] for k in ('max_inflight', 'prompt', 'prompt_version')}, 'fal_configured': bool(os.environ.get('FAL_KEY') or config.get('fal_api_key')), 'cutout_configured': bool(os.environ.get('YEZI_API_KEY') or config.get('cutout_api_key'))}

    @app.get('/api/admin/settings')
    def get_settings(request: Request):
        with db.transaction() as tx:
            admin(tx, request)
            return public_settings(tx.get('config', 'settings'))

    @app.patch('/api/admin/settings')
    def settings(data: SettingsPatch, request: Request):
        with db.transaction() as tx:
            admin(tx, request)
            config = tx.get('config', 'settings')
            if data.prompt is not None and data.prompt != config['prompt']:
                config['prompt_version'] += 1
            config.update(data.model_dump(exclude_none=True))
            tx.put('config', config)
            return public_settings(config)

    @app.post('/api/admin/invites')
    def invite(request: Request):
        with db.transaction() as tx:
            admin(tx, request)
            code = secrets.token_urlsafe(18)
            tx.put('invites', {'id': token_hash(code), 'used': False, 'expires': now() + 7 * 86400})
            return {'code': code}

    @app.get('/api/admin/users')
    def users(request: Request):
        with db.transaction() as tx:
            admin(tx, request)
            return [{**public_user(u), 'active': u['active']} for u in tx.all('users')]

    @app.patch('/api/admin/users/{id}')
    def update_user(id: str, data: ActivePatch, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            target = tx.get('users', id)
            if not target:
                raise HTTPException(404, '账号不存在')
            if id == actor['id'] and not data.active:
                raise HTTPException(400, '不能停用自己的管理员账号')
            target['active'] = data.active
            tx.put('users', target)
            return {**public_user(target), 'active': target['active']}

    def template_public(value):
        return {k: value[k] for k in ('id', 'code', 'name', 'active', 'revision', 'images')} | {'category': {'男孩': 'boy', '女孩': 'girl'}.get(value['category'], value['category'])}

    @app.get('/api/templates')
    def templates(request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            return [template_public(t) for t in tx.all('templates') if t['active'] or actor['role'] == 'admin']

    async def write_template(request, id=None):
        with db.transaction() as tx:
            admin(tx, request)
        form = await request.form(max_files=12, max_fields=10, max_part_size=25 * 1024 * 1024)
        try:
            code, name = safe_name(str(form.get('code', ''))), safe_name(str(form.get('name', '')))
            category = str(form.get('category', '男孩'))
            if category not in {'男孩', '女孩', 'boy', 'girl'}:
                raise ValueError('分类必须为男孩或女孩')
            category = {'男孩': 'boy', '女孩': 'girl'}.get(category, category)
            retained = json.loads(str(form.get('existing_ids', '[]')))
            image_order = json.loads(str(form['image_order'])) if form.get('image_order') else None
            if not isinstance(retained, list) or len(set(retained)) != len(retained):
                raise ValueError('保留图片列表无效')
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        files = form.getlist('files') or form.getlist('files[]')
        if len(retained) + len(files) != 12:
            raise HTTPException(422, '每套必须恰好12张独立图片')
        binaries = []
        for f in files:
            data = await f.read(25 * 1024 * 1024 + 1)
            if len(data) > 25 * 1024 * 1024:
                raise HTTPException(413, '单张模板不得超过25MB')
            binaries.append(normalize_image(data))
        with db.transaction() as tx:
            admin(tx, request)
            old = tx.get('templates', id) if id else None
            if id and not old:
                raise HTTPException(404, '套装不存在')
            if any(t['code'].casefold() == code.casefold() and t['id'] != id for t in tx.all('templates')):
                raise HTTPException(409, '套装编号已存在')
            available = {x['id']: x for x in old['images']} if old else {}
            if any(x not in available for x in retained):
                raise HTTPException(422, '保留图片不属于当前套装版本')
            images = [dict(available[x]) for x in retained]
            for data in binaries:
                asset = save_asset(db, tx, data, None, 'template')
                images.append({'id': asset['id'], 'url': asset['url']})
            if image_order is not None:
                try:
                    if not isinstance(image_order, list) or len(image_order) != 12:
                        raise ValueError('图片顺序必须包含12项')
                    newly_added = images[len(retained):]
                    ordered = [dict(available[entry['id']]) if set(entry) == {'id'} and entry['id'] in retained else newly_added[entry['file_index']] if set(entry) == {'file_index'} and type(entry['file_index']) is int and 0 <= entry['file_index'] < len(newly_added) else None for entry in image_order]
                    if any(x is None for x in ordered) or len({x['id'] for x in ordered}) != 12:
                        raise ValueError('图片顺序包含重复或无效引用')
                    images = ordered
                except (KeyError, TypeError, IndexError, ValueError) as exc:
                    raise HTTPException(422, '图片顺序包含重复或无效引用') from exc
            for position, image in enumerate(images, 1):
                image['position'] = position
            value = {'id': id or uid(), 'code': code, 'name': name, 'category': category, 'active': old['active'] if old else True, 'revision': old['revision'] + 1 if old else 1, 'images': images}
            tx.put('template_revisions', {**value, 'id': value['id'] + ':' + str(value['revision']), 'template_id': value['id']})
            tx.put('templates', value)
            return template_public(value)

    @app.post('/api/templates')
    async def add_template(request: Request):
        return await write_template(request)

    @app.put('/api/templates/{id}')
    async def replace_template(id: str, request: Request):
        return await write_template(request, id)

    @app.patch('/api/templates/{id}')
    def toggle_template(id: str, data: ActivePatch, request: Request):
        with db.transaction() as tx:
            admin(tx, request)
            value = tx.get('templates', id)
            if not value:
                raise HTTPException(404, '套装不存在')
            value['active'] = data.active
            tx.put('templates', value)
            return template_public(value)

    def upload_public(value):
        return {k: value[k] for k in ('id', 'offset', 'complete')}

    @app.post('/api/uploads/init')
    def upload_init(data: UploadInit, request: Request):
        if Path(data.filename).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise HTTPException(422, '只支持JPG、PNG和WebP')
        with db.transaction() as tx:
            actor = user(tx, request)
            existing = next((u for u in tx.all('uploads') if u['owner'] == actor['id'] and u['sha256'] == data.sha256.lower() and u['size'] == data.size and u['filename'] == data.filename), None)
            if existing:
                return upload_public(existing)
            value = {'id': uid(), 'owner': actor['id'], **data.model_dump(), 'sha256': data.sha256.lower(), 'offset': 0, 'complete': False}
            tx.put('uploads', value)
            return upload_public(value)

    @app.get('/api/uploads/{id}')
    def upload_status(id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'uploads', id, user(tx, request))
            return upload_public(value)

    @app.put('/api/uploads/{id}')
    async def upload_chunk(id: str, request: Request):
        try:
            offset = int(request.headers.get('Upload-Offset', '-1'))
        except ValueError:
            raise HTTPException(422, 'Upload-Offset必须是字节偏移量')
        chunk = bytearray()
        async for part in request.stream():
            chunk.extend(part)
            if len(chunk) > 4 * 1024 * 1024:
                raise HTTPException(413, '每个上传分块不得超过4MB')
        with db.transaction() as tx:
            value = owned(tx, 'uploads', id, user(tx, request))
            path = db.root / (id + '.upload')
            if offset < 0 or offset > value['offset'] or offset + len(chunk) > value['size']:
                raise HTTPException(409, '上传偏移量或长度不匹配，请查询当前进度')
            if offset < value['offset']:
                with path.open('rb') as file:
                    file.seek(offset)
                    same = file.read(len(chunk)) == chunk
                if not same or offset + len(chunk) > value['offset']:
                    raise HTTPException(409, '重复分块内容不同')
                return upload_public(value)
            if value['complete']:
                return upload_public(value)
            with path.open('r+b' if path.exists() else 'w+b') as file:
                file.seek(value['offset'])
                file.write(chunk)
                file.truncate()
                file.flush()
                os.fsync(file.fileno())
            os.chmod(path, 0o600)
            value['offset'] += len(chunk)
            tx.put('uploads', value)
            return upload_public(value)

    @app.post('/api/uploads/{id}/complete')
    def upload_complete(id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'uploads', id, user(tx, request))
            if not value['complete']:
                if value['offset'] != value['size']:
                    raise HTTPException(409, '上传尚未完成')
                data = (db.root / (id + '.upload')).read_bytes()
                if hashlib.sha256(data).hexdigest() != value['sha256']:
                    value['offset'] = 0
                    tx.put('uploads', value)
                    return JSONResponse({'detail': 'SHA256校验失败，上传进度已重置，请重新上传源文件'}, status_code=400)
                asset = save_asset(db, tx, normalize_image(data), value['owner'], 'avatar')
                value.update(complete=True, asset_id=asset['id'], url=asset['url'])
                tx.put('uploads', value)
            return {k: value[k] for k in ('id', 'filename', 'url')}

    def order_public(tx, value, full=False):
        items = [i for i in tx.all('items') if i['order_id'] == value['id']]
        completed = sum(i['status'] == 'completed' for i in items)
        failed = sum(i['status'] == 'failed' for i in items)
        unknown = sum(i['status'] == 'unknown' for i in items)
        status = 'archived' if value.get('archived') else 'paused' if value['paused'] else 'unknown' if unknown else 'failed' if failed or value.get('processing_error') else 'completed' if completed == len(items) and value.get('overview_ready') else 'processing' if any(i['status'] == 'running' for i in items) or completed else 'queued'
        result = {k: value[k] for k in ('id', 'name', 'created_at', 'paused', 'avatar_url', 'template_codes', 'print_settings', 'artifact_version')}
        result.update(status=status, total=len(items), completed=completed, failed=failed, unknown=unknown, archived=value.get('archived', False), processing_error=value.get('processing_error'))
        if full:
            result['items'] = [{k: i.get(k) for k in ('id', 'set_code', 'position', 'status', 'error', 'result_url', 'template_url', 'attempt', 'fal_request_id', 'fal_status', 'queue_position')} | {'recoverable': bool(i.get('fal_request_id')) and i['status'] == 'unknown', 'remote_reserved': bool(i.get('remote_reserved')), 'raw_available': bool(i.get('raw_result_id')), 'processing_stage': i.get('processing_stage', 'generate')} for i in items]
            result['artifacts'] = value.get('artifacts', [])
        return result

    @app.get('/api/orders')
    def orders(request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            return [order_public(tx, o) for o in reversed(tx.all('orders')) if o['owner'] == actor['id']]

    @app.post('/api/orders')
    def create_order(data: OrderCreate, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            previous = next((o for o in tx.all('orders') if o['owner'] == actor['id'] and o['client_token'] == data.client_token), None)
            if previous:
                return order_public(tx, previous, True)
            if len(set(data.template_ids)) != len(data.template_ids):
                raise HTTPException(422, '不能重复选择套装')
            if any(o['owner'] == actor['id'] and o['normalized_name'] == data.name.casefold() for o in tx.all('orders')):
                raise HTTPException(409, '当前账号已有同名订单，请修改名称')
            avatar = owned(tx, 'uploads', data.upload_id, actor)
            if avatar['owner'] != actor['id'] or not avatar['complete']:
                raise HTTPException(409, '请先完成自己的头像上传')
            sets = [tx.get('templates', id) for id in data.template_ids]
            if any(not t or not t['active'] for t in sets):
                raise HTTPException(422, '所选套装不存在或已下架')
            config = tx.get('config', 'settings')
            value = {'id': uid(), 'owner': actor['id'], 'name': data.name, 'normalized_name': data.name.casefold(), 'client_token': data.client_token, 'created_at': datetime.fromtimestamp(now(), timezone.utc).isoformat(), 'paused': False, 'archived': False, 'avatar_url': avatar['url'], 'avatar_id': avatar['asset_id'], 'template_codes': [t['code'] for t in sets], 'template_snapshots': sets, 'prompt': config['prompt'], 'prompt_version': config['prompt_version'], 'print_settings': data.print_settings.model_dump(), 'artifact_version': 0, 'artifacts': [], 'overview_ready': False, 'content_version': 0}
            tx.put('orders', value)
            for set_index, t in enumerate(sets):
                for image in t['images']:
                    tx.put('items', {'id': uid(), 'owner': actor['id'], 'order_id': value['id'], 'set_code': t['code'], 'set_index': set_index, 'position': image['position'], 'template_id': image['id'], 'template_url': image['url'], 'status': 'queued', 'error': None, 'result_url': None, 'result_id': None, 'attempt': 0, 'retry_count': 0, 'next_at': 0})
            return order_public(tx, value, True)

    @app.get('/api/orders/{id}')
    def get_order(id: str, request: Request):
        with db.transaction() as tx:
            return order_public(tx, owned(tx, 'orders', id, user(tx, request)), True)

    def change_order(id, request, action):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            if action == 'archive':
                value['archived'] = not value.get('archived', False)
                if value['archived']:
                    value['paused'] = True
            else:
                value['paused'] = action == 'pause'
                if action == 'resume':
                    value['archived'] = False
            tx.put('orders', value)
            return order_public(tx, value, True)

    @app.post('/api/orders/{id}/pause')
    def pause(id: str, request: Request):
        return change_order(id, request, 'pause')

    @app.post('/api/orders/{id}/resume')
    def resume(id: str, request: Request):
        return change_order(id, request, 'resume')

    @app.post('/api/orders/{id}/archive')
    def archive(id: str, request: Request):
        return change_order(id, request, 'archive')

    @app.post('/api/orders/{id}/items/{item_id}/rerun')
    def rerun(id: str, item_id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            item = tx.get('items', item_id)
            if not item or item['order_id'] != id:
                raise HTTPException(404, '图片不存在')
            if item['status'] in {'running', 'queued'} or item.get('remote_reserved'):
                raise HTTPException(409, '该图片正在排队或生成')
            for field in ('fal_request_id', 'fal_status', 'fal_status_url', 'fal_response_url', 'fal_error', 'queue_position', 'raw_result_id'):
                item.pop(field, None)
            item.update(status='queued', error=None, retry_count=0, next_at=0, processing_stage='generate')
            tx.put('items', item)
            value.update(overview_ready=False, content_version=value['content_version'] + 1)
            tx.put('orders', value)
            return order_public(tx, value, True)

    @app.post('/api/orders/{id}/items/{item_id}/resolve')
    def resolve_item(id: str, item_id: str, data: ResolveUnknown, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            value = owned(tx, 'orders', id, actor)
            item = tx.get('items', item_id)
            if not item or item['order_id'] != id:
                raise HTTPException(404, '图片不存在')
            if item['status'] != 'unknown':
                raise HTTPException(409, '仅可确认待确认请求已经结束')
            item.setdefault('resolution_history', []).append({'resolved_at': now(), 'resolved_by': actor['id'], 'fal_request_id': item.get('fal_request_id'), 'fal_status': item.get('fal_status'), 'error': item.get('error')})
            item.update(status='failed', remote_reserved=False, error='已人工确认原请求结束；可单独选择重跑')
            tx.put('items', item)
            return order_public(tx, value, True)

    @app.post('/api/orders/{id}/items/{item_id}/recover')
    def recover_item(id: str, item_id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            item = tx.get('items', item_id)
            if not item or item['order_id'] != id:
                raise HTTPException(404, '图片不存在')
            if item['status'] != 'unknown' or not item.get('fal_request_id'):
                raise HTTPException(409, '仅可恢复有FAL编号的待确认请求')
            item.update(status='queued', next_at=0, error=None, remote_reserved=True)
            tx.put('items', item)
            return order_public(tx, value, True)

    @app.post('/api/orders/{id}/items/{item_id}/reprocess')
    def reprocess(id: str, item_id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            item = tx.get('items', item_id)
            if not item or item['order_id'] != id:
                raise HTTPException(404, '图片不存在')
            if item['status'] in {'running', 'queued'} or item.get('remote_reserved'):
                raise HTTPException(409, '该图片正在排队或处理')
            if not item.get('raw_result_id') or not tx.get('assets', item['raw_result_id']):
                raise HTTPException(409, '没有可恢复的原始生成结果')
            item.update(status='queued', processing_stage='postprocess', error=None, retry_count=0, next_at=0)
            tx.put('items', item)
            value.update(overview_ready=False, processing_error=None, content_version=value['content_version'] + 1)
            tx.put('orders', value)
            return order_public(tx, value, True)

    @app.post('/api/orders/{id}/repack')
    def repack(id: str, data: Repack, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            value.update(print_settings=data.print_settings.model_dump(), content_version=value['content_version'] + 1, overview_ready=False, processing_error=None)
            tx.put('orders', value)
        app.state.worker.publish(id, force=True)
        with db.transaction() as tx:
            return order_public(tx, tx.get('orders', id), True)

    @app.post('/api/orders/{id}/watermark')
    def watermark(id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            value['content_version'] += 1
            value.update(overview_ready=False, processing_error=None)
            tx.put('orders', value)
        app.state.worker.publish(id, watermark_only=True, force=True)
        with db.transaction() as tx:
            return order_public(tx, tx.get('orders', id), True)

    @app.get('/api/orders/{id}/manifest')
    def manifest(id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            public = order_public(tx, value)
            return {'order_id': id, 'name': value['name'], 'version': value['artifact_version'], 'complete': public['completed'] == public['total'] and value.get('overview_ready', False), 'files': value['artifacts']}

    @app.get('/api/orders/{id}/download.zip')
    def download_zip(id: str, request: Request):
        with db.transaction() as tx:
            value = owned(tx, 'orders', id, user(tx, request))
            if not value['artifacts']:
                raise HTTPException(409, '暂时没有已完成的打印文件')
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                for a in value['artifacts']:
                    archive.writestr(value['name'] + '/' + a['path'], asset_bytes(db, tx.get('assets', a['id'])))
            output.seek(0)
            return StreamingResponse(output, media_type='application/zip', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + __import__('urllib.parse', fromlist=['quote']).quote(value['name'] + '.zip')})

    @app.get('/api/assets/{id}')
    def asset(id: str, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            value = tx.get('assets', id)
            if not value or value['kind'] != 'template' and value['owner'] != actor['id'] and actor['role'] != 'admin':
                raise HTTPException(404, '文件不存在')
            return FileResponse(db.root / 'assets' / value['file'], media_type='image/png')

    frontend_dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if frontend_dist.exists():
        @app.get('/{path:path}', include_in_schema=False)
        def frontend(path: str):
            candidate = (frontend_dist / path).resolve()
            if not candidate.is_relative_to(frontend_dist.resolve()) or path.startswith('api/'):
                raise HTTPException(404, '页面不存在')
            return FileResponse(candidate if candidate.is_file() else frontend_dist / 'index.html')
    return app


def app_factory():
    return create_app()
