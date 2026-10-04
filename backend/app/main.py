"""Private local Avatar Sticker Studio HTTP API."""
import asyncio
import hashlib
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response, Query
from typing import Literal
from starlette.datastructures import UploadFile
from starlette.routing import Match
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from .auth import same_organization, require_superadmin, managed_user, hash_password, owned, public_user, require_admin, require_user, token_hash, verify_password
from .db import Database, uid
from .schemas import AccountPatch, ActivePatch, Credentials, CleanupConfirm, CleanupPreview, PasswordChange, PrintSettings, SettingsPatch, Signup, UploadInit
from .storage import asset_bytes, normalize_image, save_asset
from .providers import DEFAULT_MAX_UPLOADS, DEFAULT_UPLOAD_TIMEOUT
from .maintenance import account_deletion_plan, cleanup_plan, drain_cleanup, stage_cleanup, storage_stats
from .statistics import summarize
from .previews import PreviewCache
from .media_cache import MediaCache, MediaWarmer
from .auth import can_read_asset, generation_limit, DEFAULT_GENERATION_CONCURRENCY
from .schemas import AccountConcurrencyPatch, AccountDeleteConfirm, AdminCreateUser


def create_app(data_root=None, provider=None, clock=None, start_worker=True):
    db = Database(data_root or os.environ.get('STUDIO_DATA_DIR', '.data'))
    now = clock or time.time

    @asynccontextmanager
    async def lifespan(app):
        from .worker import Worker
        drain_cleanup(db)
        app.state.worker = Worker(db, provider=provider, clock=now)
        app.state.worker.before_publish = app.state.agiso_worker.submitted_remark
        if start_worker:
            await app.state.worker.start()
            await app.state.agiso_worker.start()
            app.state.media_warmer.start()
        yield
        if start_worker:
            await asyncio.to_thread(app.state.media_warmer.stop)
            await app.state.agiso_worker.stop()
            await app.state.worker.stop()

    app = FastAPI(title='Avatar Sticker Studio', lifespan=lifespan)
    app.state.db, app.state.clock = db, now
    app.state.preview_cache = PreviewCache(db)
    app.state.media_cache = MediaCache(db)
    app.state.media_warmer = MediaWarmer(db, app.state.media_cache)
    from .agiso_worker import AgisoWorker
    app.state.agiso_worker = AgisoWorker(db, now)

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
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers.setdefault('Cache-Control', 'no-store')
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

    def superadmin(tx, request):
        actor = user(tx, request)
        require_superadmin(actor)
        return actor

    def session(tx, response, value):
        token = secrets.token_urlsafe(32)
        tx.put('sessions', {'id': token_hash(token), 'user_id': value['id'], 'expires': now() + 7 * 86400})
        response.set_cookie('studio_session', token, max_age=7 * 86400, httponly=True, samesite='strict', secure=os.environ.get('STUDIO_SECURE_COOKIE') == '1', path='/')
        return public_user(value)

    def register_user(tx, data, role, organization_id=None):
        if any(u['username'].casefold() == data.username.casefold() for u in tx.all('users')):
            raise HTTPException(409, '用户名已存在')
        value = {'id': uid(), 'username': data.username, 'password': hash_password(data.password), 'display_name': data.display_name.strip(), 'role': role, 'watermark': '', 'print_defaults': PrintSettings().model_dump(), 'active': True}
        organization_id = organization_id or tx.get('migrations','organizations-v1')['default_organization_id']
        organization = tx.get('organizations', organization_id)
        if not organization or not organization['active']: raise HTTPException(403, '组织已停用')
        value.update(organization_id=organization_id, organization_name=organization['name'])
        value['generation_concurrency'] = DEFAULT_GENERATION_CONCURRENCY
        tx.put('users', value)
        return value

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/ready')
    def ready():
        worker = getattr(app.state, 'worker', None)
        try:
            with db.transaction() as tx:
                config = tx.get('config', 'settings')
                lease = tx.get('workers', worker.id) if worker else None
            active = bool(config and worker and not worker.stopping and
                          worker.loop_task and not worker.loop_task.done() and
                          worker.lease_task and not worker.lease_task.done() and
                          lease and lease['expires'] > now())
        except Exception:
            active = False
        return JSONResponse({'status': 'ready' if active else 'not_ready'}, status_code=200 if active else 503)

    @app.get('/api/staff-guide')
    def staff_guide(request: Request, response: Response):
        # Authorize before reading content; guest sessions cannot satisfy user().
        db.read(lambda tx: user(tx, request))
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Vary'] = 'Cookie, X-Studio-User'
        guide = Path(__file__).resolve().parents[1] / 'content' / 'staff-guide.json'
        return json.loads(guide.read_text(encoding='utf-8'))

    @app.get('/api/auth/status')
    def auth_status(request: Request):
        def read(tx):
            try:
                value = public_user(user(tx, request))
            except HTTPException:
                value = None
            return {'needs_setup': os.environ.get('STUDIO_ALLOW_SETUP') != '0' and not tx.all('users'), 'user': value}
        return db.read(read)

    @app.post('/api/auth/setup')
    def setup(data: Signup, response: Response, request: Request):
        if os.environ.get('STUDIO_ALLOW_SETUP') == '0':
            raise HTTPException(403, '首次管理员设置已禁用')
        if request.client and request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
            raise HTTPException(403, '首次管理员设置仅允许本机访问')
        with db.transaction() as tx:
            if tx.all('users'):
                raise HTTPException(409, '管理员已设置，请登录或使用邀请码')
            return session(tx, response, register_user(tx, data, 'superadmin'))

    @app.post('/api/auth/register')
    def register(data: Signup, response: Response):
        with db.transaction() as tx:
            invite = tx.get('invites', token_hash(data.invite or ''))
            if not invite or invite['used'] or invite['expires'] < now():
                raise HTTPException(400, '邀请码无效、已使用或已过期')
            value = register_user(tx, data, 'staff', invite.get('organization_id'))
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
            organization = tx.get('organizations', value.get('organization_id','')) if value else None
            valid = value and verify_password(data.password, value['password']) and value['active'] and (value['role']=='superadmin' or organization and organization['active'])
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
        return db.read(lambda tx: public_user(user(tx, request)))

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
        return {**{k: config[k] for k in ('max_inflight', 'prompt', 'prompt_version')}, 'max_uploads': config.get('max_uploads', DEFAULT_MAX_UPLOADS), 'fal_upload_timeout': config.get('fal_upload_timeout', DEFAULT_UPLOAD_TIMEOUT), 'fal_configured': bool(os.environ.get('FAL_KEY') or config.get('fal_api_key')), 'cutout_configured': bool(os.environ.get('YEZI_API_KEY') or config.get('cutout_api_key')),
                'fal_balance_configured': bool(os.environ.get('FAL_ADMIN_KEY') or config.get('fal_admin_key')),
                'fal_balance_key_source': 'environment' if os.environ.get('FAL_ADMIN_KEY') else 'settings' if config.get('fal_admin_key') else None}

    @app.get('/api/admin/settings')
    def get_settings(request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
            return public_settings(tx.get('config', 'settings'))

    @app.patch('/api/admin/settings')
    def settings(data: SettingsPatch, request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
            config = tx.get('config', 'settings')
            if data.prompt is not None and data.prompt != config['prompt']:
                config['prompt_version'] += 1
            config.update(data.model_dump(exclude_none=True))
            tx.put('config', config)
            return public_settings(config)

    @app.get('/api/admin/fal/balance')
    def fal_balance(request: Request, response: Response):
        def credential(tx):
            superadmin(tx, request)
            return os.environ.get('FAL_ADMIN_KEY') or tx.get('config', 'settings').get('fal_admin_key')
        key = db.read(credential)
        if not key:
            raise HTTPException(409, '请先保存 FAL ADMIN Key，再查询余额')
        from .fal_billing import fetch_balance
        # Network I/O must not hold a database transaction/write lock.
        result = fetch_balance(key)
        current_key = db.read(credential)  # Revalidate session/role after I/O.
        if current_key != key:
            raise HTTPException(409, '余额查询密钥已变化，请重新查询')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Vary'] = 'Cookie, X-Studio-User'
        return {**result, 'queried_at': now()}

    @app.get('/api/statistics')
    def personal_statistics(request: Request, days: Literal["0", "1", "3", "7", "30"] = "30", offset: int = Query(480, ge=-720, le=840)):
        with db.transaction() as tx:
            actor = user(tx, request)
            return summarize(tx, actor, now(), int(days), offset)

    @app.get('/api/admin/statistics')
    def global_statistics(request: Request, days: Literal["0", "1", "3", "7", "30"] = "30", offset: int = Query(480, ge=-720, le=840)):
        with db.transaction() as tx:
            actor = superadmin(tx, request)
            return summarize(tx, actor, now(), int(days), offset, global_scope=True)

    @app.get('/api/admin/storage')
    def storage(request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
        return storage_stats(db, app.state.media_warmer)

    @app.post('/api/admin/cleanup/preview')
    def cleanup_preview(data: CleanupPreview, request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
            return cleanup_plan(db, tx, data.before)[0]

    @app.post('/api/admin/cleanup')
    def cleanup(data: CleanupConfirm, request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
            plan, records, paths = cleanup_plan(db, tx, data.before)
            if not secrets.compare_digest(plan['preview_token'], data.preview_token):
                raise HTTPException(409, '订单状态已变化，请重新预览清理范围')
            stage_cleanup(tx, records, paths)
        pending = drain_cleanup(db)
        return {'deleted_orders':plan['order_count'], 'pending_files':pending, 'storage':storage_stats(db, app.state.media_warmer)}

    @app.post('/api/admin/cleanup/retry')
    def cleanup_retry(request: Request):
        with db.transaction() as tx:
            superadmin(tx, request)
        return {'pending_files':drain_cleanup(db), 'storage':storage_stats(db, app.state.media_warmer)}

    @app.post('/api/admin/invites')
    def invite(request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            code = secrets.token_urlsafe(18)
            tx.put('invites', {'id': token_hash(code), 'organization_id':actor['organization_id'], 'used': False, 'expires': now() + 7 * 86400})
            return {'code': code}

    @app.post('/api/admin/users')
    def create_member(data: AdminCreateUser, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            temporary = secrets.token_urlsafe(18)
            member = register_user(tx, Signup(username=data.username, display_name=data.display_name, password=temporary), 'staff', actor['organization_id'])
            return {'user': public_user(member) | {'active':True}, 'temporary_password':temporary}

    @app.post('/api/admin/users/{id}/password')
    def reset_member_password(id: str, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            target = managed_user(tx, id, actor)
            if not target: raise HTTPException(404, '账号不存在')
            if target['role']=='superadmin' or target['role']=='org_admin' and actor['role']!='superadmin': raise HTTPException(403, '管理员请在账号设置中修改自己的密码')
            temporary = secrets.token_urlsafe(18)
            target['password']=hash_password(temporary)
            tx.put('users', target)
            for entry in tx.all('sessions'):
                if entry['user_id']==id: tx.delete('sessions', entry['id'])
            return {'temporary_password':temporary}

    @app.get('/api/admin/users/{id}/concurrency')
    def member_concurrency(id: str, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            target = managed_user(tx, id, actor)
            if not target: raise HTTPException(404, '账号不存在')
            return {'generation_concurrency':generation_limit(target)}

    @app.patch('/api/admin/users/{id}/concurrency')
    def update_member_concurrency(id: str, data: AccountConcurrencyPatch, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            target = managed_user(tx, id, actor)
            if not target: raise HTTPException(404, '账号不存在')
            if generation_limit(target) != data.expected_limit:
                raise HTTPException(409, '账号并行上限已变化，请重新确认')
            target['generation_concurrency'] = data.generation_concurrency
            tx.put('users', target)
            return {'generation_concurrency':generation_limit(target)}

    @app.get('/api/admin/users/{id}/deletion')
    def preview_member_deletion(id: str, request: Request):
        with db.transaction() as tx:
            managed_user(tx, id, admin(tx, request))
            return account_deletion_plan(tx, id)[0]

    @app.delete('/api/admin/users/{id}')
    def delete_member(id: str, data: AccountDeleteConfirm, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            managed_user(tx, id, actor)
            plan, records, paths = account_deletion_plan(tx, id)
            if data.username != records['users'][0]['username']:
                raise HTTPException(409, '输入的用户名不匹配，请重新确认')
            if not plan['can_delete']:
                raise HTTPException(409, '该账号有正在处理或结果待核对的任务，请处理完成后再删除')
            if not secrets.compare_digest(data.preview_token, plan['preview_token']):
                raise HTTPException(409, '账号数据已变化，请重新预览删除范围')
            stage_cleanup(tx, records, paths)
        return {'deleted':True, 'pending_files':drain_cleanup(db)}

    @app.get('/api/admin/users')
    def users(request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            return [{**public_user(u), 'active': u['active']} for u in tx.all('users') if actor['role']=='superadmin' or same_organization(u, actor) and u['role']!='superadmin']

    @app.patch('/api/admin/users/{id}')
    def update_user(id: str, data: ActivePatch, request: Request):
        with db.transaction() as tx:
            actor = admin(tx, request)
            target = managed_user(tx, id, actor)
            if not target:
                raise HTTPException(404, '账号不存在')
            if id == actor['id'] and not data.active:
                raise HTTPException(400, '不能停用自己的管理员账号')
            target['active'] = data.active
            tx.put('users', target)
            return {**public_user(target), 'active': target['active']}

    from .organizations import register_organizations
    register_organizations(app, db, user, register_user)

    from .customer_orders import register_customer_orders
    register_customer_orders(app, db, user)
    from .agiso_routes import register_agiso
    register_agiso(app, db, user)

    from .library import register_library
    register_library(app, db, user)

    def upload_public(value):
        return {k: value[k] for k in ('id', 'offset', 'complete')}

    @app.post('/api/uploads/init')
    def upload_init(data: UploadInit, request: Request):
        if Path(data.filename).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise HTTPException(422, '只支持JPG、PNG和WebP')
        with db.transaction() as tx:
            actor = user(tx, request)
            existing = next((u for u in tx.all('uploads') if not u.get('guest_order_id') and same_organization(u, actor) and u['sha256'] == data.sha256.lower() and u['size'] == data.size and u['filename'] == data.filename), None)
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
                asset = save_asset(db, tx, normalize_image(data, 'avatar'), value['owner'], 'avatar')
                value.update(complete=True, asset_id=asset['id'], url=asset['url'])
                tx.put('uploads', value)
            return {k: value[k] for k in ('id', 'filename', 'url')}

    @app.get('/api/assets/{id}/preview')
    def asset_preview(id: str, request: Request, size: int = 320):
        # Authenticate before cache lookup AND before returning 304.
        with db.transaction() as tx:
            actor = user(tx, request)
            value = tx.get('assets', id)
            if not can_read_asset(value, actor):
                raise HTTPException(404, '文件不存在')
        if size not in (320, 1280):
            raise HTTPException(422, '不支持的预览尺寸')
        cache = app.state.preview_cache
        etag = cache.etag(value, size)
        headers = {'Cache-Control': 'private, no-cache', 'Vary': 'Cookie', 'ETag': etag}
        candidates = [tag.strip().removeprefix('W/') for tag in request.headers.get('if-none-match', '').split(',')]
        if '*' in candidates or etag.removeprefix('W/') in candidates:
            return Response(status_code=304, headers=headers)
        return Response(cache.get(value, size), media_type='image/webp', headers=headers)

    @app.get('/api/assets/{id}')
    def asset(id: str, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            value = tx.get('assets', id)
            if not can_read_asset(value, actor):
                raise HTTPException(404, '文件不存在')
            return FileResponse(db.root / 'assets' / value['file'], media_type='image/png')

    @app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'], include_in_schema=False)
    def missing_api(path: str, request: Request):
        # Unknown APIs must not be mistaken for the SPA's GET route (405).
        allowed = set()
        for route in app.routes:
            if getattr(route, 'endpoint', None) is missing_api or not getattr(route, 'path', '').startswith('/api/'):
                continue
            if route.matches(request.scope)[0] == Match.PARTIAL:
                allowed.update(route.methods or ())
        if allowed:
            raise HTTPException(405, 'Method Not Allowed', headers={'Allow': ', '.join(sorted(allowed))})
        raise HTTPException(404, '接口不存在')

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
