"""Organization customer orders: immutable work, independent slots and guest-safe DTOs."""
import hashlib
import io
import json
import os
import secrets
import re
import unicodedata
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator, model_validator
from .auth import token_hash
from .db import uid
from .schemas import Model, PrintSettings, UploadInit, safe_name
from .storage import asset_bytes, normalize_image, save_asset

COOKIE = 'studio_guest'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class OpenOrder(Model):
    order_number: str = Field(min_length=1, max_length=100)
    generation_limit: int = Field(ge=1, le=360, strict=True)
    final_count: int = Field(ge=1, le=360, strict=True)
    rerun_limit: int = Field(ge=0, strict=True)
    notes: str = Field('', max_length=2000)
    client_token: str = Field(min_length=1, max_length=120)
    _number = field_validator('order_number')(safe_name)

    @model_validator(mode='after')
    def limits(self):
        if self.final_count > self.generation_limit:
            raise ValueError('最终数量不能超过生成上限')
        return self


class Mutation(Model):
    client_token: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=1, strict=True)


class AvatarSelection(Model):
    upload_id: str
    template_ids: list[str] = Field(default_factory=list, max_length=360)
    sticker_ids: list[str] = Field(default_factory=list, max_length=360)


class Generate(Mutation):
    avatars: list[AvatarSelection] = Field(min_length=1, max_length=360)


class Select(Mutation):
    version_id: str


class Submit(Mutation):
    slot_ids: list[str] = Field(min_length=1, max_length=360)


class Repack(Mutation):
    print_settings: PrintSettings | None = None


class SellerRemark(Mutation):
    remark: str = Field('', max_length=2000)


class Resolve(Mutation):
    confirmed_ended: Literal[True]


class Login(Model):
    order_number: str = Field(min_length=1, max_length=100)


class WatermarkPreview(Model):
    ids: list[str] = Field(min_length=1, max_length=360)


class WatermarkApply(WatermarkPreview):
    preview_token: str
    client_token: str = Field(min_length=1, max_length=120)


def scoped(value, actor):
    return bool(value and (actor.get('role') == 'superadmin' or
                          value.get('organization_id') and value.get('organization_id') == actor.get('organization_id')))


def customer(tx, id):
    value = tx.get('orders', id)
    if not value or value.get('workflow_version') != 3:
        raise HTTPException(404, '订单不存在')
    return value


def guest_order(tx, request, now):
    session = tx.get('guest_sessions', token_hash(request.cookies.get(COOKIE, '')))
    if not session or session['expires'] <= now:
        raise HTTPException(401, '请使用订单号登录')
    order = customer(tx, session['order_id'])
    organization = tx.get('organizations', order.get('organization_id', ''))
    if organization and not organization.get('active', True):
        raise HTTPException(401, '订单暂不可用')
    return order


def media_url(order, asset_id, guest=True):
    prefix = f"/api/guest/media/{order['id']}" if guest else f"/api/customer-orders/{order['id']}/media"
    return f"{prefix}/{asset_id}?v={order['media_version']}" if asset_id else None


def reconcile(tx, order):
    """Consume/release each finished reservation once, including after recovery."""
    changed = False
    for slot in order['slots']:
        item = tx.get('items', slot.get('active_item_id', ''))
        if not item:
            continue
        if item['status'] == 'completed' and item.get('result_id'):
            version = {'id': item['id'], 'asset_id': item['result_id'], 'item_id': item['id']}
            if not any(v['id'] == version['id'] for v in slot['versions']):
                slot['versions'].append(version)
                if slot.get('reservation_item_id') == item['id']:
                    slot['reruns_reserved'] -= 1
                    slot['reruns_used'] += 1
                    slot['reservation_item_id'] = None
                    slot['pending_version_id'] = version['id']
                else:
                    slot['selected_version_id'] = version['id']
                changed = True
        elif item['status'] == 'failed' and not item.get('remote_reserved') and not item.get('cutout_inflight') and slot.get('reservation_item_id') == item['id']:
            slot['reruns_reserved'] -= 1
            slot['reservation_item_id'] = None
            changed = True
    if changed:
        order['version'] += 1
        order['content_version'] += 1
        tx.put('orders', order)
    return order


def dto(tx, order, guest=False):
    reconcile(tx, order)
    if guest and order['state'] == 'cancelled':
        return {k: order[k] for k in ('id', 'order_number', 'state')}
    result = {k: order[k] for k in ('id', 'order_number', 'state', 'version', 'generation_limit', 'final_count', 'rerun_limit', 'created_at')}
    from .agiso_service import order_allowed
    effective_hold=bool(integration_held(order) or order.get('agiso_id') and not order_allowed(tx,order))
    result.update(paused=bool(order.get('paused') or effective_hold),
                  hold_reason=('订单售后处理中，请联系工作人员' if integration_held(order) else '订单暂不可操作，请联系工作人员') if effective_hold else None)
    result.update(preview_url=media_url(order, order.get('overview_id'), guest) if order.get('overview_ready') else None,
                  delivery_ready=order['state'] == 'submitted' and bool(order.get('delivery_ready')))
    if not guest or order['state'] != 'submitted':
        result['avatars'] = [{'id': a['id'], 'name': a['name'], 'preview_url': media_url(order, a['asset_id'], guest)} for a in order['avatars']]
        result['slots'] = []
        for slot in order['slots']:
            item = tx.get('items', slot.get('active_item_id', ''))
            row = {k: slot[k] for k in ('id', 'avatar_id', 'sticker_code', 'reruns_used', 'reruns_reserved', 'selected_version_id', 'pending_version_id')}
            row['status'] = item['status'] if item else 'queued'
            row['versions'] = [{'id': v['id'], 'preview_url': media_url(order, v['asset_id'], guest)} for v in slot['versions']]
            if item and item.get('error'):
                row['error'] = '生成未完成，请联系工作人员处理' if guest else item['error']
            if not guest:
                row['raw_available'] = bool(item and item.get('raw_result_id'))
                row['needs_resolution'] = bool(item and (item['status'] == 'unknown' or item.get('cutout_inflight') or item.get('remote_reserved') and item['status'] == 'failed'))
            result['slots'].append(row)
    if not guest:
        owner = tx.get('users', order['owner']) or {}
        result.update({k: order[k] for k in ('owner', 'notes', 'organization_id', 'watermark', 'print_settings', 'delivery_version')})
        result['owner_name'] = owner.get('display_name', '')
        result['processing_error'] = order.get('processing_error')
        result['buyer_memo'] = order.get('buyer_memo', '')
        result['platform_remark'] = order.get('platform_remark', '')
    return result


def operation(tx, scope, body, action):
    key = digest([scope, body.client_token])
    fingerprint = digest([action, body.model_dump()])
    prior = tx.get('customer_operations', key)
    if prior and prior['fingerprint'] != fingerprint:
        raise HTTPException(409, '操作编号已用于不同请求')
    return key, fingerprint, prior


def remember(tx, key, fingerprint, order_id):
    tx.put('customer_operations', {'id': key, 'fingerprint': fingerprint, 'order_id': order_id})


def audit(tx, order, action, actor, now):
    tx.put('customer_audit', {'id': uid(), 'order_id': order['id'], 'organization_id': order['organization_id'],
                            'actor': actor, 'action': action, 'version': order['version'], 'at': now})


def library_records(tx, order):
    allowed = lambda x: x.get('active') and not x.get('deleted') and x.get('organization_id') == order['organization_id']
    return [s for s in tx.all('stickers') if allowed(s)], [t for t in tx.all('templates') if allowed(t)]


def expand(tx, order, body, is_guest):
    if len(body.avatars) > order['final_count'] or len({a.upload_id for a in body.avatars}) != len(body.avatars):
        raise HTTPException(422, '头像数量须为1至最终数量，且不能重复使用同一头像记录')
    stickers, templates = library_records(tx, order)
    by_sticker, by_template = {s['id']: s for s in stickers}, {t['id']: t for t in templates}
    avatars, occurrences, unique = [], [], {}
    for selection in body.avatars:
        upload = tx.get('uploads', selection.upload_id)
        if not upload or not upload.get('complete') or upload.get('organization_id') != order['organization_id'] or (upload.get('guest_order_id') and upload['guest_order_id'] != order['id']) or (is_guest and upload.get('guest_order_id') != order['id']):
            raise HTTPException(422, '头像尚未上传完成或不可用')
        avatar = {'id': upload['id'], 'asset_id': upload['asset_id'], 'name': upload['filename']}
        avatars.append(avatar)
        ids = []
        for tid in selection.template_ids:
            t = by_template.get(tid)
            if not t or not t.get('sticker_ids'):
                raise HTTPException(422, '所选模板不可用')
            ids.extend(t['sticker_ids'])
        ids.extend(selection.sticker_ids)
        if not ids:
            raise HTTPException(422, '每个头像至少选择一张贴纸')
        for sid in ids:
            s = by_sticker.get(sid)
            if not s:
                raise HTTPException(422, '所选贴纸不可用')
            key = (avatar['id'], s['id'], s['revision'])
            unique.setdefault(key, {'id': uid(), 'avatar': avatar, 'sticker': deepcopy(s)})
            occurrences.append((avatar, s, unique[key]['id']))
            if len(occurrences) > order['generation_limit']:
                raise HTTPException(422, '选择数量超过订单生成上限')
    if len(occurrences) < order['final_count']:
        raise HTTPException(422, '选择数量不能少于最终数量')
    return avatars, occurrences, list(unique.values())


def new_item(tx, order, id, avatar_id, sticker, now, position):
    item = {'id': id, 'order_id': order['id'], 'owner': order['owner'], 'organization_id': order['organization_id'],
            'workflow_version': 3, 'credit_exempt': True, 'avatar_id': avatar_id, 'sticker_id': sticker['id'],
            'sticker_revision': sticker['revision'], 'template_id': sticker['image']['id'],
            'set_index': 0, 'set_code': 'customer', 'position': position, 'status': 'queued', 'attempt': 0,
            'next_at': 0, 'remote_reserved': False, 'result_id': None, 'error': None}
    generation = {'id': uid(), 'owner': order['owner'], 'organization_id': order['organization_id'], 'item_id': id,
                  'order_id': order['id'], 'status': 'exempt', 'created_at': datetime.fromtimestamp(now, timezone.utc).isoformat()}
    item['generation_id'] = generation['id']
    tx.put('generations', generation)
    tx.put('items', item)
    return item


def delivery_folder(order):
    label = order['order_number'] + ('_' + order['notes'].strip() if order['notes'].strip() else '')
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', unicodedata.normalize('NFC', label))
    label = label.strip().rstrip('. ') or order['id']
    encoded = label.encode('utf-8')
    if len(encoded) > 220:
        suffix = '_' + hashlib.sha256(encoded).hexdigest()[:12]
        label = encoded[:220-len(suffix)].decode('utf-8', errors='ignore').rstrip('. ') + suffix
    return label


def create_customer_order(tx, actor, data, at):
    """Shared creation path snapshots owner defaults for every order source."""
    config = tx.get('config', 'settings')
    order = {'id': uid(), **data.model_dump(exclude={'client_token'}), 'workflow_version': 3,
             'owner': actor['id'], 'organization_id': actor['organization_id'], 'state': 'draft', 'version': 1,
             'name': data.order_number, 'watermark': actor.get('watermark', '').strip() or actor['display_name'],
             'watermark_version': 1, 'media_version': 1, 'print_settings': actor['print_defaults'],
             'avatars': [], 'slots': [], 'created_at': datetime.fromtimestamp(at, timezone.utc).isoformat(),
             'prompt': config['prompt'], 'prompt_version': config.get('prompt_version', 1), 'paused': False,
             'content_version': 1, 'artifact_version': 0, 'delivery_version': 0, 'delivery_ready': False,
             'artifacts': [], 'overview_ready': False, 'overview_id': None, 'publish_signatures': {}}
    tx.put('orders', order)
    return order


def integration_held(order):
    return bool(order.get('integration_holds'))


def require_active_order(order, tx=None):
    if tx is not None and order.get('agiso_id'):
        from .agiso_service import order_allowed
        if not order_allowed(tx, order):
            raise HTTPException(409, '订单暂不可操作，请联系工作人员')
    if order.get('paused') or integration_held(order) or order.get('state') == 'cancelled':
        raise HTTPException(409, '订单暂不可操作，请联系工作人员')


def register_customer_orders(app, db, user):
    now = app.state.clock

    def access(tx, request, id=None, guest=False):
        if guest:
            order = guest_order(tx, request, now())
            return order, 'guest:' + order['id']
        actor = user(tx, request)
        order = customer(tx, id)
        if not scoped(order, actor):
            raise HTTPException(404, '订单不存在')
        return order, actor['id']

    @app.post('/api/customer-orders')
    def open_order(data: OpenOrder, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            if not actor.get('organization_id'):
                raise HTTPException(409, '请先关联组织')
            key, fingerprint, prior = operation(tx, actor['id'], data, 'open')
            if prior:
                return dto(tx, customer(tx, prior['order_id']))
            if any(o.get('order_number') == data.order_number for o in tx.all('orders')):
                raise HTTPException(409, '订单号已使用')
            order = create_customer_order(tx, actor, data, now())
            remember(tx, key, fingerprint, order['id'])
            audit(tx, order, 'open', actor['id'], now())
            return dto(tx, order)

    @app.get('/api/customer-orders')
    def list_orders(request: Request, state: str | None = None, owner: str | None = None, order_number: str | None = None,
                    date_from: str | None = None, date_to: str | None = None):
        with db.transaction() as tx:
            actor = user(tx, request)
            orders = [o for o in tx.all('orders') if o.get('workflow_version') == 3 and scoped(o, actor)]
            return [dto(tx, o) for o in reversed(orders) if (not state or o['state'] == state) and (not owner or o['owner'] == owner)
                    and (not order_number or order_number in o['order_number']) and (not date_from or o['created_at'][:10] >= date_from)
                    and (not date_to or o['created_at'][:10] <= date_to)]

    def watermarks(tx, actor, ids):
        if len(set(ids)) != len(ids):
            raise HTTPException(422, '订单不可重复')
        orders = [customer(tx, id) for id in ids]
        if any(not scoped(o, actor) for o in orders):
            raise HTTPException(404, '订单不存在')
        rows = []
        for order in orders:
            opener = tx.get('users', order['owner'])
            mark = opener.get('watermark', '').strip() or opener['display_name']
            rows.append({'id': order['id'], 'order_number': order['order_number'], 'watermark': mark})
        fingerprint = digest([[o['id'], o['version'], row['watermark']] for o, row in zip(orders, rows)])
        return orders, rows, fingerprint

    @app.post('/api/customer-orders/watermarks/preview')
    def preview_watermarks(data: WatermarkPreview, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            _, rows, fingerprint = watermarks(tx, actor, data.ids)
            token = secrets.token_urlsafe(32)
            tx.put('watermark_previews', {'id': token_hash(token), 'actor': actor['id'], 'fingerprint': fingerprint, 'expires': now() + 900})
            return {'orders': rows, 'preview_token': token}

    @app.post('/api/customer-orders/watermarks')
    def apply_watermarks(data: WatermarkApply, request: Request):
        with db.transaction() as tx:
            actor = user(tx, request)
            key, fingerprint, prior = operation(tx, actor['id'], data, 'watermarks')
            if prior:
                return {'updated': len(data.ids)}
            orders, rows, snapshot = watermarks(tx, actor, data.ids)
            confirmation = tx.get('watermark_previews', token_hash(data.preview_token))
            if not confirmation or confirmation['actor'] != actor['id'] or confirmation['expires'] < now() or confirmation['fingerprint'] != snapshot:
                raise HTTPException(409, '水印设置或订单已变化，请重新预览')
            for order, row in zip(orders, rows):
                order.update(watermark=row['watermark'], watermark_version=order['watermark_version']+1,
                             media_version=order['media_version']+1, version=order['version']+1, content_version=order['content_version']+1,
                             overview_ready=False, processing_error=None)
                tx.put('orders', order)
                audit(tx, order, 'watermark', actor['id'], now())
            remember(tx, key, fingerprint, None)
        return {'updated': len(data.ids)}

    @app.get('/api/customer-orders/{id}')
    def get_order(id: str, request: Request):
        with db.transaction() as tx:
            order, _ = access(tx, request, id)
            return dto(tx, order)

    @app.post('/api/guest/login')
    def login(data: Login, request: Request, response: Response):
        denied = None
        with db.transaction() as tx:
            # Durable IP and credential buckets; never save attempted plaintext order numbers.
            keys = [digest(['ip', request.client.host if request.client else 'unknown']), digest(['number', data.order_number.strip()])]
            buckets = []
            for key in keys:
                b = tx.get('guest_login_limits', key) or {'id': key, 'started': now(), 'attempts': 0}
                if now() - b['started'] >= 900:
                    b.update(started=now(), attempts=0)
                buckets.append(b)
            if any(b['attempts'] >= 12 for b in buckets):
                denied = (429, '尝试次数过多，请稍后再试')
            else:
                order = next((o for o in tx.all('orders') if o.get('workflow_version') == 3 and o['order_number'] == data.order_number.strip()), None)
                organization = tx.get('organizations', order.get('organization_id', '')) if order else None
                if not order or organization and not organization.get('active', True):
                    for b in buckets:
                        b['attempts'] += 1
                        tx.put('guest_login_limits', b)
                    denied = (401, '订单号无效')
                else:
                    for linked in tx.all('agiso_orders'):
                        if linked.get('customer_order_id') == order['id']:
                            linked['entered_at'] = now()
                            tx.put('agiso_orders', linked)
                    token = secrets.token_urlsafe(32)
                    tx.put('guest_sessions', {'id': token_hash(token), 'order_id': order['id'], 'expires': now()+7*86400})
                    response.set_cookie(COOKIE, token, max_age=7*86400, httponly=True, samesite='strict', secure=os.environ.get('STUDIO_SECURE_COOKIE') == '1', path='/api/guest')
                    result = dto(tx, order, True)
        if denied:
            raise HTTPException(*denied)
        return result

    @app.post('/api/guest/logout')
    def logout(request: Request, response: Response):
        with db.transaction() as tx:
            tx.delete('guest_sessions', token_hash(request.cookies.get(COOKIE, '')))
        response.delete_cookie(COOKIE, path='/api/guest')
        return {'ok': True}

    @app.get('/api/guest/order')
    def current_order(request: Request):
        with db.transaction() as tx:
            return dto(tx, guest_order(tx, request, now()), True)

    @app.get('/api/guest/library')
    def guest_library(request: Request):
        with db.transaction() as tx:
            order = guest_order(tx, request, now())
            if order['state'] not in {'draft', 'review'}:
                raise HTTPException(409, '当前订单不能浏览图库')
            stickers, templates = library_records(tx, order)
            def image(s):
                url = media_url(order, s['image']['id'])
                return {'id': s['image']['id'], 'code': s['code'], 'url': url, 'preview_url': url}
            by_id = {s['id']: s for s in stickers}
            return {'stickers': [{**{k:s.get(k, '') for k in ('id', 'code', 'name', 'category', 'revision')}, 'image': image(s), 'preview_url': image(s)['url']} for s in stickers],
                    'templates': [{**{k:t.get(k, '') for k in ('id', 'code', 'name', 'category')}, 'sticker_ids': t['sticker_ids'],
                                   'images': [image(by_id[s]) for s in t['sticker_ids'] if s in by_id],
                                   'preview_url': image(by_id[t['sticker_ids'][0]])['url'] if t['sticker_ids'] and t['sticker_ids'][0] in by_id else None} for t in templates]}

    def mutate(request, data, action, id=None, guest=False, slot_id=None):
        with db.transaction() as tx:
            order, actor = access(tx, request, id, guest)
            if action not in {'cancel', 'restore', 'resolve', 'repack'}:
                require_active_order(order, tx)
            if action == 'restore' and integration_held(order):
                raise HTTPException(409, '售后处理中的订单不能恢复')
            key, fingerprint, prior = operation(tx, order['id'], data, [action, slot_id])
            if prior:
                return dto(tx, order, guest)
            reconcile(tx, order)
            if data.expected_version != order['version']:
                raise HTTPException(409, '订单已变化，请刷新后重试')
            state = order['state']
            if action in {'generate', 'preflight'}:
                if state != 'draft':
                    raise HTTPException(409, '订单选择已冻结')
                avatars, occurrences, unique = expand(tx, order, data, guest)
                if action == 'preflight':
                    return {'avatar_count': len(avatars), 'selection_count': len(occurrences), 'generation_count': len(unique)}
                order['avatars'] = avatars
                for position, entry in enumerate(unique):
                    new_item(tx, order, entry['id'], entry['avatar']['asset_id'], entry['sticker'], now(), position)
                order['slots'] = [{'id': uid(), 'avatar_id': a['id'], 'sticker_code': s['code'], 'sticker': deepcopy(s),
                                   'active_item_id': item_id, 'initial_item_id': item_id, 'versions': [], 'reruns_used': 0,
                                   'reruns_reserved': 0, 'selected_version_id': None, 'pending_version_id': None}
                                  for a, s, item_id in occurrences]
                order.update(state='review', generation_count=len(unique), selection_count=len(occurrences))
            elif action in {'rerun', 'select', 'retry', 'resolve', 'reprocess'}:
                if state != 'review':
                    raise HTTPException(409, '当前订单不能修改结果')
                slot = next((s for s in order['slots'] if s['id'] == slot_id), None)
                if not slot:
                    raise HTTPException(404, '贴纸位置不存在')
                item = tx.get('items', slot['active_item_id'])
                if action in {'retry', 'resolve', 'reprocess'}:
                    if guest:
                        raise HTTPException(403, '需要工作人员处理')
                    if action == 'resolve':
                        if item['status'] not in {'unknown', 'failed'}:
                            raise HTTPException(409, '该任务不需要人工核对')
                        item.update(status='failed', remote_reserved=False, error='工作人员已确认原请求结束')
                        item.pop('cutout_inflight', None)
                        item.pop('cutout_started_at', None)
                        tx.put('items', item)
                        reconcile(tx, order)
                    elif action == 'reprocess':
                        if not item.get('raw_result_id') or item['status'] not in {'failed', 'unknown'} or item.get('cutout_inflight') or item.get('remote_reserved'):
                            raise HTTPException(409, '请先核对原请求，或暂无可恢复原图')
                        if slot['reruns_used']+slot['reruns_reserved'] >= order['rerun_limit'] and item['id'] != slot['initial_item_id']:
                            raise HTTPException(409, '该位置重跑次数已用完')
                        if item['id'] != slot['initial_item_id'] and not slot.get('reservation_item_id'):
                            slot.update(reservation_item_id=item['id'], reruns_reserved=slot['reruns_reserved']+1)
                        item.update(status='queued', processing_stage='postprocess', next_at=0, error=None)
                        tx.put('items', item)
                    else:
                        if item['status'] != 'failed' or item.get('remote_reserved') or item.get('cutout_inflight') or item.get('raw_result_id') or item['id'] != slot['initial_item_id']:
                            raise HTTPException(409, '仅可重试确定失败的首次生成；已有原图请恢复处理')
                        avatar = next(a for a in order['avatars'] if a['id'] == slot['avatar_id'])
                        replacement = new_item(tx, order, uid(), avatar['asset_id'], slot['sticker'], now(), len(tx.all('items')))
                        # Initial duplicates share retry work, preserving deduplication and history.
                        for linked in order['slots']:
                            if linked['initial_item_id'] == item['id'] and linked['active_item_id'] == item['id']:
                                linked.update(initial_item_id=replacement['id'], active_item_id=replacement['id'])
                elif action == 'rerun':
                    if item['status'] not in {'completed', 'failed'} or item.get('remote_reserved') or item.get('cutout_inflight') or slot['pending_version_id']:
                        raise HTTPException(409, '请等待生成并选择待确认结果')
                    if slot['reruns_used'] + slot['reruns_reserved'] >= order['rerun_limit']:
                        raise HTTPException(409, '该位置重跑次数已用完')
                    avatar = next(a for a in order['avatars'] if a['id'] == slot['avatar_id'])
                    item = new_item(tx, order, uid(), avatar['asset_id'], slot['sticker'], now(), len(tx.all('items')))
                    slot.update(active_item_id=item['id'], reservation_item_id=item['id'], reruns_reserved=slot['reruns_reserved']+1)
                else:
                    if not any(v['id'] == data.version_id for v in slot['versions']):
                        raise HTTPException(422, '所选版本不可用')
                    slot.update(selected_version_id=data.version_id, pending_version_id=None)
            elif action == 'submit':
                if state != 'review':
                    raise HTTPException(409, '当前订单不能提交')
                if len(data.slot_ids) != order['final_count'] or len(set(data.slot_ids)) != len(data.slot_ids):
                    raise HTTPException(422, '必须按顺序选择规定数量的不同贴纸位置')
                for slot in order['slots']:
                    item = tx.get('items', slot['active_item_id'])
                    if (slot['pending_version_id'] or slot['reruns_reserved'] or slot.get('reservation_item_id') or
                            item['status'] in {'running', 'queued', 'unknown'} or item.get('remote_reserved') or item.get('cutout_inflight')):
                        raise HTTPException(409, '尚有生成、请求核对或版本选择待处理')
                frozen = []
                by_slot = {s['id']: s for s in order['slots']}
                for sid in data.slot_ids:
                    slot = by_slot.get(sid)
                    version = next((v for v in slot['versions'] if v['id'] == slot['selected_version_id']), None) if slot else None
                    if not version:
                        raise HTTPException(422, '所选位置没有可用结果')
                    frozen.append({'slot_id': sid, **deepcopy(version)})
                order.update(state='submitted', final_entries=frozen, delivery_ready=False, delivery_version=order['delivery_version']+1,
                             overview_ready=False, media_version=order['media_version']+1, processing_error=None)
            elif action == 'cancel':
                if state == 'cancelled':
                    raise HTTPException(409, '订单已取消')
                order.update(prior_state=state, state='cancelled', paused=True, media_version=order['media_version']+1)
            elif action == 'restore':
                if state != 'cancelled':
                    raise HTTPException(409, '订单未取消')
                order.update(state=order['prior_state'], paused=False, media_version=order['media_version']+1, processing_error=None)
            elif action == 'unlock':
                if state != 'submitted':
                    raise HTTPException(409, '仅已提交订单可解锁')
                order.update(state='review', delivery_ready=False, overview_ready=False, artifacts=[], overview_id=None,
                             media_version=order['media_version']+1, final_entries=[], publish_signatures={})
            elif action == 'repack':
                if state != 'submitted':
                    raise HTTPException(409, '仅已提交订单可重新排版')
                if data.print_settings:
                    order['print_settings'] = data.print_settings.model_dump()
                order.update(delivery_ready=False, delivery_version=order['delivery_version']+1, processing_error=None, publish_signatures={})
            elif action == 'remark':
                if guest:
                    raise HTTPException(403, '需要工作人员处理')
                remark = ' '.join(data.remark.split())[:2000]
                if remark != order.get('platform_remark', ''):
                    order['platform_remark'] = remark
                    if order['state'] == 'submitted':
                        order.update(delivery_ready=False, delivery_version=order['delivery_version']+1, publish_signatures={})
            order['version'] += 1
            order['content_version'] += 1
            tx.put('orders', order)
            remember(tx, key, fingerprint, order['id'])
            audit(tx, order, action, actor, now())
            result = dto(tx, order, guest)
        return result

    # Named wrappers preserve FastAPI's typed request parsing and separate staff/guest authority.
    for guest, prefix in ((False, '/api/customer-orders/{id}'), (True, '/api/guest/order')):
        def endpoints(is_guest):
            def generate(data: Generate, request: Request, id: str | None = None): return mutate(request, data, 'generate', id, is_guest)
            def preflight(data: Generate, request: Request, id: str | None = None): return mutate(request, data, 'preflight', id, is_guest)
            def rerun(slot_id: str, data: Mutation, request: Request, id: str | None = None): return mutate(request, data, 'rerun', id, is_guest, slot_id)
            def select(slot_id: str, data: Select, request: Request, id: str | None = None): return mutate(request, data, 'select', id, is_guest, slot_id)
            def submit(data: Submit, request: Request, id: str | None = None): return mutate(request, data, 'submit', id, is_guest)
            return [('generate', generate), ('preflight', preflight), ('slots/{slot_id}/rerun', rerun), ('slots/{slot_id}/select', select), ('submit', submit)]
        for suffix, endpoint in endpoints(guest):
            app.add_api_route(prefix+'/'+suffix, endpoint, methods=['POST'])
    for name in ('cancel', 'restore', 'unlock'):
        def staff_endpoint(action):
            def endpoint(id: str, data: Mutation, request: Request): return mutate(request, data, action, id)
            return endpoint
        app.add_api_route('/api/customer-orders/{id}/'+name, staff_endpoint(name), methods=['POST'])

    @app.post('/api/customer-orders/{id}/slots/{slot_id}/resolve')
    def resolve(id: str, slot_id: str, data: Resolve, request: Request):
        return mutate(request, data, 'resolve', id, slot_id=slot_id)

    for recovery in ('retry', 'reprocess'):
        def recovery_endpoint(action):
            def endpoint(id: str, slot_id: str, data: Mutation, request: Request):
                return mutate(request, data, action, id, slot_id=slot_id)
            return endpoint
        app.add_api_route('/api/customer-orders/{id}/slots/{slot_id}/'+recovery, recovery_endpoint(recovery), methods=['POST'])

    @app.post('/api/customer-orders/{id}/repack')
    def repack(id: str, data: Repack, request: Request):
        return mutate(request, data, 'repack', id)

    @app.post('/api/customer-orders/{id}/remark')
    def remark(id: str, data: SellerRemark, request: Request):
        return mutate(request, data, 'remark', id)

    def delivery(tx, request, id):
        order, _ = access(tx, request, id)
        if order['state'] != 'submitted' or not order.get('delivery_ready'):
            raise HTTPException(409, '订单尚未完成交付')
        return order

    @app.get('/api/customer-orders/{id}/manifest')
    def manifest(id: str, request: Request):
        with db.transaction() as tx:
            order = delivery(tx, request, id)
            return {'order_id': id, 'order_number': order['order_number'], 'name': delivery_folder(order), 'notes': order['notes'],
                    'version': order['delivery_version'], 'folder_name': delivery_folder(order), 'complete': True, 'files': [a for a in order['artifacts'] if a['kind'] == 'print']}

    @app.get('/api/customer-orders/{id}/download.zip')
    def download(id: str, request: Request):
        with db.transaction() as tx:
            order = delivery(tx, request, id)
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                for a in order['artifacts']:
                    if a['kind'] == 'print':
                        archive.writestr(delivery_folder(order)+'/'+a['path'], asset_bytes(db, tx.get('assets', a['id'])))
            return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="order.zip"'})

    def guest_upload(tx, request, id=None, writable=False):
        order = guest_order(tx, request, now())
        require_active_order(order, tx)
        if order['state'] not in {'draft', 'review'} or writable and order['state'] != 'draft':
            raise HTTPException(409, '当前订单不能上传头像')
        value = tx.get('uploads', id) if id else None
        if id and (not value or value.get('guest_order_id') != order['id']):
            raise HTTPException(404, '上传记录不存在')
        return order, value

    def upload_dto(order, value):
        return {k: value[k] for k in ('id', 'filename', 'size', 'offset', 'complete')} | {'preview_url': media_url(order, value.get('asset_id'))}

    @app.post('/api/guest/uploads/init')
    def upload_init(data: UploadInit, request: Request):
        if Path(data.filename).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise HTTPException(422, '只支持JPG、PNG和WebP')
        with db.transaction() as tx:
            order, _ = guest_upload(tx, request, writable=True)
            existing = next((u for u in tx.all('uploads') if u.get('guest_order_id') == order['id'] and u['sha256'] == data.sha256.lower() and u['size'] == data.size and u['filename'] == data.filename), None)
            if existing:
                return upload_dto(order, existing)
            if sum(u.get('guest_order_id') == order['id'] for u in tx.all('uploads')) >= 360:
                raise HTTPException(422, '头像上传数量已达上限')
            value = {'id': uid(), 'owner': order['owner'], 'organization_id': order['organization_id'], 'guest_order_id': order['id'],
                     **data.model_dump(), 'sha256': data.sha256.lower(), 'offset': 0, 'complete': False}
            tx.put('uploads', value)
            return upload_dto(order, value)

    @app.get('/api/guest/uploads/{id}')
    def upload_status(id: str, request: Request):
        with db.transaction() as tx:
            order, value = guest_upload(tx, request, id)
            return upload_dto(order, value)

    @app.put('/api/guest/uploads/{id}')
    async def upload_chunk(id: str, request: Request):
        # Authenticate before reading potentially large request streams.
        with db.transaction() as tx:
            guest_upload(tx, request, id, True)
        try:
            offset = int(request.headers.get('Upload-Offset', '-1'))
        except ValueError:
            raise HTTPException(422, '上传偏移量无效')
        chunk = bytearray()
        async for part in request.stream():
            chunk.extend(part)
            if len(chunk) > 4 * 1024 * 1024:
                raise HTTPException(413, '每块不得超过4MB')
        with db.transaction() as tx:
            order, value = guest_upload(tx, request, id, True)
            path = db.root / (id+'.upload')
            if offset < 0 or offset > value['offset'] or offset+len(chunk) > value['size']:
                raise HTTPException(409, '上传偏移量不匹配')
            if offset < value['offset']:
                with path.open('rb') as file:
                    file.seek(offset)
                    same = file.read(len(chunk)) == chunk
                if not same or offset+len(chunk) > value['offset']:
                    raise HTTPException(409, '重复分块内容不同')
            elif not value['complete']:
                with path.open('r+b' if path.exists() else 'w+b') as file:
                    file.seek(offset); file.write(chunk); file.truncate(); file.flush(); os.fsync(file.fileno())
                os.chmod(path, 0o600)
                value['offset'] += len(chunk)
                tx.put('uploads', value)
            return upload_dto(order, value)

    @app.post('/api/guest/uploads/{id}/complete')
    def upload_complete(id: str, request: Request):
        with db.transaction() as tx:
            order, value = guest_upload(tx, request, id, True)
            if not value['complete']:
                if value['offset'] != value['size']:
                    raise HTTPException(409, '上传尚未完成')
                data = (db.root/(id+'.upload')).read_bytes()
                if hashlib.sha256(data).hexdigest() != value['sha256']:
                    value['offset'] = 0
                    tx.put('uploads', value)
                    return JSONResponse({'detail': '文件校验失败，请重新上传'}, status_code=400)
                asset = save_asset(db, tx, normalize_image(data), order['owner'], 'avatar', order_id=order['id'])
                value.update(complete=True, asset_id=asset['id'])
                tx.put('uploads', value)
            return upload_dto(order, value)

    from .guest_media import register_guest_media
    register_guest_media(app, db, user)
