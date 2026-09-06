"""Durable queue with cross-process admission and conservative uncertain outcomes."""
import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from .db import uid
from .processing import decode, encode, overview, pack_set
from .providers import FalProvider, ProviderFailure, YeziProvider
from .schemas import PrintSettings
from .storage import asset_bytes, save_asset

log = logging.getLogger(__name__)
# Production runs one Uvicorn process. Serialize both HTTP and background
# publishers before loading their snapshots and allocating large image packs.
_publish_lock = threading.Lock()
CUTOUT_UNCERTAIN = '抠图请求可能已计费，结果待确认；原始图片和已有结果已保留，请人工选择重新处理，不会自动重试'


class Worker:
    def __init__(self, db, provider=None, clock=None):
        self.db, self.provider, self.clock = db, provider, clock or time.time
        self.id = uid()
        self.tasks = set()
        self.loop_task = None
        self.lease_task = None
        self.stopping = False

    def recover(self):
        with self.db.transaction() as tx:
            now = self.clock()
            for item in tx.all('items'):
                if item['status'] == 'running':
                    owner = tx.get('workers', item.get('worker_id', ''))
                    if not owner or owner['expires'] < now:
                        if item.get('cutout_inflight'):
                            item.update(status='unknown', remote_reserved=False, error=CUTOUT_UNCERTAIN)
                        elif item.get('raw_result_id'):
                            item.update(status='queued', processing_stage='postprocess', next_at=0, remote_reserved=False)
                        elif item.get('fal_request_id'):
                            item.update(status='queued', next_at=0, remote_reserved=True)
                        else:
                            item.update(status='unknown', remote_reserved=True, error='服务中断时请求可能已发出，结果待确认；不会自动重新提交')
                        tx.put('items', item)
            for owner in tx.all('workers'):
                if owner['expires'] < now:
                    tx.delete('workers', owner['id'])

    def heartbeat(self):
        with self.db.transaction() as tx:
            tx.put('workers', {'id': self.id, 'expires': self.clock() + 30})

    def claim(self):
        with self.db.transaction() as tx:
            now = self.clock()
            tx.put('workers', {'id': self.id, 'expires': now + 30})
            config = tx.get('config', 'settings')
            configured = self.provider is not None or bool(os.environ.get('FAL_KEY') or config.get('fal_api_key'))
            items = tx.all('items')
            generation_inflight = sum(bool(i.get('remote_reserved')) for i in items)
            processing_inflight = sum(i['status'] == 'running' and i.get('processing_stage') == 'postprocess' for i in items)
            generation_admitted = configured and generation_inflight < config['max_inflight'] and now >= config.get('fal_retry_at', 0)
            orders = {o['id']: o for o in tx.all('orders')}
            active_users = {u['id'] for u in tx.all('users') if u['active']}
            candidates = [i for i in items if i['status'] == 'queued' and not i.get('cutout_inflight') and i.get('next_at', 0) <= now]
            # Recovery and saved-image processing do not compete for new remote slots.
            candidates.sort(key=lambda i: 0 if i.get('fal_request_id') or i.get('processing_stage') == 'postprocess' else 1)
            item = next((i for i in candidates if
                (i.get('processing_stage') == 'postprocess' and processing_inflight < 2 and not orders[i['order_id']]['paused'] and i['owner'] in active_users) or
                (i.get('fal_request_id') and i.get('processing_stage') != 'postprocess' and configured) or
                (i.get('processing_stage') != 'postprocess' and generation_admitted and not orders[i['order_id']]['paused'] and i['owner'] in active_users)), None)
            if not item:
                return None
            postprocess = item.get('processing_stage') == 'postprocess'
            new_request = not postprocess and not item.get('fal_request_id')
            item.update(status='running', worker_id=self.id, run_id=uid(), attempt=item['attempt'] + int(new_request), started_at=now, error=None)
            if not postprocess:
                item['remote_reserved'] = True
            tx.put('items', item)
            return item

    async def execute(self, item):
        if not item:
            return
        response_received = False
        try:
            with self.db.transaction() as tx:
                current = tx.get('items', item['id'])
                if current['status'] != 'running' or current.get('worker_id') != self.id:
                    return
                if current.get('cutout_inflight'):
                    raise ProviderFailure(CUTOUT_UNCERTAIN, 'unknown')
                order = tx.get('orders', item['order_id'])
                config = tx.get('config', 'settings')
                template = asset_bytes(self.db, tx.get('assets', item['template_id']))
                avatar = asset_bytes(self.db, tx.get('assets', order['avatar_id']))
            if item.get('processing_stage') == 'postprocess':
                with self.db.transaction() as tx:
                    raw_asset = tx.get('assets', item.get('raw_result_id', ''))
                    if not raw_asset:
                        raise ProviderFailure('没有可恢复的原始生成结果')
                    data = asset_bytes(self.db, raw_asset)
                response_received = True
                image = decode(data, require_transparency=False)
            else:
                provider = self.provider or FalProvider(os.environ.get('FAL_KEY') or config.get('fal_api_key', ''))
                if hasattr(provider, 'submit'):
                    if not item.get('fal_request_id'):
                        job = await provider.submit(template=template, avatar=avatar, prompt=order['prompt'])
                        self.checkpoint(item, **job)
                        return self.defer(item, 2)
                    if item.get('fal_status') != 'COMPLETED':
                        progress = await provider.poll(item)
                        self.checkpoint(item, **progress)
                        item.update(progress)
                        if progress['fal_status'] != 'COMPLETED':
                            return self.defer(item, 2)
                    if item.get('fal_error'):
                        raise ProviderFailure(item['fal_error'], 'failed')
                    data = await provider.result(item)
                else:
                    data = await provider.generate(template=template, avatar=avatar, prompt=order['prompt'])
                response_received = True
                image = decode(data, require_transparency=False)
                if image.size != (1024, 1024):
                    raise ProviderFailure('API图片尺寸不是约定的1024×1024，已拒绝发布')
                with self.db.transaction() as tx:
                    latest = tx.get('items', item['id'])
                    if latest['status'] != 'running' or latest.get('worker_id') != self.id or latest.get('run_id') != item.get('run_id'):
                        return
                    raw = save_asset(self.db, tx, encode(image), item['owner'], 'raw_result', order_id=item['order_id'])
                    latest.update(raw_result_id=raw['id'], remote_reserved=False, processing_stage='postprocess')
                    tx.put('items', latest)
            if image.getchannel('A').getextrema()[0] == 255:
                key = os.environ.get('YEZI_API_KEY') or config.get('cutout_api_key')
                if not key:
                    raise ProviderFailure('图片缺少透明背景；请管理员配置抠图API。原始生成图片已保留')
                # Commit before entering the provider, including its admission wait.
                # A lost response cannot safely be distinguished from a paid call.
                with self.db.transaction() as tx:
                    latest = tx.get('items', item['id'])
                    if latest['status'] != 'running' or latest.get('worker_id') != self.id or latest.get('run_id') != item.get('run_id'):
                        return
                    if latest.get('cutout_inflight'):
                        raise ProviderFailure(CUTOUT_UNCERTAIN, 'unknown')
                    latest.update(cutout_inflight=True, cutout_started_at=self.clock())
                    tx.put('items', latest)
                data = await YeziProvider(self.db, key, self.clock).cutout(data)
                image = decode(data)
            else:
                image = decode(data)
            with self.db.transaction() as tx:
                latest = tx.get('items', item['id'])
                if latest['status'] != 'running' or latest.get('worker_id') != self.id or latest.get('run_id') != item.get('run_id'):
                    return
                result = save_asset(self.db, tx, encode(image), item['owner'], 'result', order_id=item['order_id'])
                latest.pop('cutout_inflight', None)
                latest.pop('cutout_started_at', None)
                latest.update(status='completed', remote_reserved=False, result_id=result['id'], result_url=result['url'], error=None)
                tx.put('items', latest)
                order = tx.get('orders', item['order_id'])
                order['content_version'] += 1
                tx.put('orders', order)
            await asyncio.to_thread(self.publish, item['order_id'])
        except asyncio.CancelledError:
            # Read the durable stage: execute's original claim may predate raw save.
            with self.db.transaction() as tx:
                latest = tx.get('items', item['id'])
            self.fail(item, ProviderFailure('请求执行时服务停止，保留原请求', 'retry' if latest.get('fal_request_id') or latest.get('raw_result_id') else 'unknown'))
            raise
        except ProviderFailure as exc:
            self.fail(item, exc)
        except Exception as exc:
            # Once a request starts, unexpected failures must not trigger another paid request.
            self.fail(item, ProviderFailure('结果处理失败：' + (str(exc)[:180] if isinstance(exc, ValueError) else type(exc).__name__) + '；不会自动重新生图', 'failed' if response_received else 'unknown'))

    def checkpoint(self, item, **fields):
        with self.db.transaction() as tx:
            latest = tx.get('items', item['id'])
            if latest.get('run_id') == item.get('run_id') and latest.get('worker_id') == self.id:
                latest.update(fields)
                tx.put('items', latest)

    def defer(self, item, delay):
        self.checkpoint(item, status='queued', next_at=self.clock() + delay)

    def fail(self, item, error):
        with self.db.transaction() as tx:
            latest = tx.get('items', item['id'])
            if not latest or latest['status'] != 'running' or latest.get('worker_id') != self.id or latest.get('run_id') != item.get('run_id'):
                return
            if latest.get('cutout_inflight'):
                latest.update(status='failed' if error.status == 'failed' else 'unknown', remote_reserved=False, error=CUTOUT_UNCERTAIN + '；' + str(error))
                tx.put('items', latest)
                return
            retries = latest.get('retry_count', 0)
            known = bool(latest.get('fal_request_id'))
            if error.status == 'retry' and (known or retries < 3):
                latest.update(status='queued', retry_count=retries + 1, next_at=self.clock() + max(error.retry_after, min(600, 15 * 2 ** min(retries, 6))), error=str(error))
            else:
                latest.update(status='failed' if error.status == 'retry' else error.status, error=str(error))
            if error.status == 'retry' and not known:
                config = tx.get('config', 'settings')
                config['fal_retry_at'] = max(config.get('fal_retry_at', 0), latest.get('next_at', self.clock() + error.retry_after))
                tx.put('config', config)
            if error.status == 'failed' or (error.status == 'retry' and not known):
                latest['remote_reserved'] = False
            tx.put('items', latest)

    def publish(self, order_id, force=False, watermark_only=False):
        with _publish_lock:
            return self._publish(order_id, force=force, watermark_only=watermark_only)

    def _publish(self, order_id, force=False, watermark_only=False):
        try:
            with self.db.transaction() as tx:
                order = tx.get('orders', order_id)
                if not order:
                    return False
                owner = tx.get('users', order['owner'])
                items = sorted([i for i in tx.all('items') if i['order_id'] == order_id], key=lambda i: (i['set_index'], i['position']))
                snapshot = order['content_version']
                binaries = {i['id']: asset_bytes(self.db, tx.get('assets', i['result_id'])) for i in items if i.get('result_id')}
            settings = PrintSettings(**order['print_settings'])
            old_signatures = order.get('publish_signatures', {})
            signatures = dict(old_signatures)
            replacements = {}
            if not watermark_only:
                for code in order['template_codes']:
                    group = [i for i in items if i['set_code'] == code]
                    if len(group) != 12 or any(not i.get('result_id') for i in group):
                        continue
                    signature = hashlib.sha256(json.dumps([settings.model_dump(), [i['result_id'] for i in group]], sort_keys=True).encode()).hexdigest()
                    if not force and signature == old_signatures.get(code):
                        continue
                    replacements[code] = pack_set([binaries[i['id']] for i in group], order['name'], code, settings)
                    signatures[code] = signature
            ready = len(binaries) == len(items) and all(i['status'] == 'completed' for i in items)
            watermark = owner['watermark'] or owner['display_name']
            overview_signature = hashlib.sha256(json.dumps([[i.get('result_id') for i in items], watermark, 'bold-outline-shadow-v3']).encode()).hexdigest()
            new_overview = None
            if ready and (force or old_signatures.get('_overview') != overview_signature):
                new_overview = overview([binaries[i['id']] for i in items], watermark)
                signatures['_overview'] = overview_signature
            if not replacements and new_overview is None:
                return False
            with self.db.transaction() as tx:
                latest = tx.get('orders', order_id)
                if not latest or latest['content_version'] != snapshot:
                    return False
                artifacts = latest['artifacts']
                by_code = {}
                for code in order['template_codes']:
                    if code in replacements:
                        group = []
                        for filename, data in replacements[code]:
                            a = save_asset(self.db, tx, data, order['owner'], 'print', order_id=order_id)
                            group.append({k: a[k] for k in ('id', 'url', 'sha256', 'size', 'kind')} | {'path': filename, 'set_code': code})
                        by_code[code] = group
                    else:
                        by_code[code] = [a for a in artifacts if a.get('set_code') == code]
                artifacts = [a for code in order['template_codes'] for a in by_code[code]]
                if new_overview is not None:
                    latest['overview_style'] = 'bold-outline-shadow-v3'
                    a = save_asset(self.db, tx, new_overview, order['owner'], 'overview', order_id=order_id)
                    artifacts.append({k: a[k] for k in ('id', 'url', 'sha256', 'size', 'kind')} | {'path': order['name'] + '_水印总览.png'})
                else:
                    artifacts.extend(a for a in latest['artifacts'] if a['kind'] == 'overview')
                latest.update(artifacts=artifacts, artifact_version=latest['artifact_version'] + 1, overview_ready=ready, publish_signatures=signatures, processing_error=None)
                tx.put('orders', latest)
            return True
        except Exception as exc:
            with self.db.transaction() as tx:
                latest = tx.get('orders', order_id)
                if not latest:
                    return False
                latest['processing_error'] = '排版或总览处理失败：' + (str(exc)[:200] if isinstance(exc, ValueError) else type(exc).__name__) + '；已有文件保留，可重新排版'
                tx.put('orders', latest)
            return False

    async def start(self):
        self.recover()
        self.heartbeat()
        self.lease_task = asyncio.create_task(self.maintain_lease())
        self.loop_task = asyncio.create_task(self.run())

    async def maintain_lease(self):
        while not self.stopping:
            await asyncio.to_thread(self.heartbeat)
            await asyncio.sleep(5)

    async def run(self):
        while not self.stopping:
            try:
                self.heartbeat()
                self.recover()
                # Startup or racing publishers may have saved images but not their derived files.
                with self.db.transaction() as tx:
                    pending = [o['id'] for o in tx.all('orders') if (not o.get('overview_ready') or o.get('overview_style') != 'bold-outline-shadow-v3') and not o.get('processing_error')]
                for id in pending:
                    await asyncio.to_thread(self.publish, id)
                while not self.stopping:
                    item = self.claim()
                    if not item:
                        break
                    task = asyncio.create_task(self.execute(item))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
            except Exception:
                log.exception('Worker scheduling error')
            await asyncio.sleep(1)

    async def stop(self):
        self.stopping = True
        if self.lease_task:
            self.lease_task.cancel()
            await asyncio.gather(self.lease_task, return_exceptions=True)
        if self.loop_task:
            self.loop_task.cancel()
            await asyncio.gather(self.loop_task, return_exceptions=True)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        with self.db.transaction() as tx:
            tx.delete('workers', self.id)
