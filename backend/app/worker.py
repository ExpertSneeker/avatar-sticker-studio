"""Durable queue with cross-process admission and conservative uncertain outcomes."""
import asyncio
import json
import logging
import os
import threading
import time
from collections import Counter
from .auth import generation_limit
from .db import uid
from .agiso_service import order_allowed
from . import request_tracking, oss_delivery
from .processing import decode, encode
from .providers import DEFAULT_MAX_UPLOADS, DEFAULT_UPLOAD_TIMEOUT, CutoutDeferred, FalProvider, ProviderFailure, YeziProvider
from .storage import asset_bytes, save_asset

log = logging.getLogger(__name__)
# Uvicorn's default config does not install a root handler for application INFO.
# Give only these safe records a dedicated stderr sink (captured by systemd),
# with propagation disabled to avoid duplicates or enabling HTTPX/SDK URL logs.
timing_log = logging.getLogger(__name__ + '.timing')
timing_log.setLevel(logging.INFO)
timing_log.propagate = False
if not timing_log.handlers:
    timing_log.addHandler(logging.StreamHandler())
# Production runs one Uvicorn process. Serialize both HTTP and background
# publishers before loading their snapshots and allocating large image packs.
_publish_lock = threading.Lock()
CUTOUT_UNCERTAIN = '抠图请求可能已计费，结果待确认；原始图片和已有结果已保留，请人工选择重新处理，不会自动重试'


class LazyRecords:
    """Mapping view like {r['id']: r for r in tx.all(kind)}, loading only requested records."""
    def __init__(self, tx, kind):
        self.tx, self.kind, self.cache = tx, kind, {}

    def __getitem__(self, id):
        if id not in self.cache:
            self.cache[id] = self.tx.get(self.kind, id)
        if self.cache[id] is None:
            raise KeyError(id)
        return self.cache[id]


class Worker:
    def __init__(self, db, provider=None, clock=None):
        self.db, self.provider, self.clock = db, provider, clock or time.time
        self.id = uid()
        self.tasks = set()
        self.before_publish = None
        self.loop_task = None
        self.lease_task = None
        self.stopping = False
        self.oss_next_sync = 0
        self.oss_task = None

    def recover(self):
        with self.db.transaction() as tx:
            now = self.clock()
            for item in tx.where('items', 'status', 'running'):
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
                        request_tracking.progress(tx, item)
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
            # Only queued, running or remotely reserved items affect admission; the rest cannot be chosen or counted.
            items = tx.find('items', ("json_extract(doc,'$.status') IN ('queued','running')", ()), ("json_extract(doc,'$.remote_reserved') = 1", ()))
            generation_inflight = sum(bool(i.get('remote_reserved')) for i in items)
            owner_inflight = Counter(i['owner'] for i in items if i.get('remote_reserved'))
            processing_inflight = sum(i['status'] == 'running' and i.get('processing_stage') == 'postprocess' for i in items)
            # No request ID yet: admission covers OSS staging plus the FAL POST.
            # Providers without a separate submit step (test doubles) have no upload phase to cap.
            uploading = sum(i['status'] == 'running' and i.get('processing_stage') != 'postprocess' and not i.get('fal_request_id') for i in items)
            upload_admitted = not (self.provider is None or hasattr(self.provider, 'submit')) or uploading < config.get('max_uploads', DEFAULT_MAX_UPLOADS)
            generation_admitted = configured and upload_admitted and generation_inflight < config['max_inflight'] and now >= config.get('fal_retry_at', 0)
            orders = LazyRecords(tx, 'orders')
            active_users = {u['id']: u for u in tx.all('users') if u['active']}
            candidates = [i for i in items if i['status'] == 'queued' and not i.get('cutout_inflight') and i.get('next_at', 0) <= now]
            eligible = [i for i in candidates if
                (i.get('processing_stage') == 'postprocess' and processing_inflight < 2 and order_allowed(tx, orders[i['order_id']]) and not orders[i['order_id']]['paused'] and i['owner'] in active_users) or
                (i.get('fal_request_id') and i.get('processing_stage') != 'postprocess' and configured) or
                (i.get('processing_stage') != 'postprocess' and generation_admitted and order_allowed(tx, orders[i['order_id']]) and not orders[i['order_id']]['paused'] and i['owner'] in active_users
                 and owner_inflight[i['owner']] < generation_limit(active_users[i['owner']]))]
            # Prefer the least occupied account, rotating ties durably even with one slot.
            # Recovery and saved-image processing never need a new generation slot.
            item = min(eligible, key=lambda i: (0, 0, 0) if i.get('fal_request_id') or i.get('processing_stage') == 'postprocess'
                       else (1, owner_inflight[i['owner']], active_users[i['owner']].get('last_generation_dispatch', 0)), default=None)
            if not item:
                return None
            postprocess = item.get('processing_stage') == 'postprocess'
            new_request = not postprocess and not item.get('fal_request_id')
            if new_request:
                config['dispatch_sequence'] = config.get('dispatch_sequence', 0) + 1
                account = active_users[item['owner']]
                account['last_generation_dispatch'] = config['dispatch_sequence']
                tx.put('users', account)
                tx.put('config', config)
            item.update(status='running', worker_id=self.id, run_id=uid(), attempt=item['attempt'] + int(new_request), started_at=now, error=None)
            if not postprocess:
                item['remote_reserved'] = True
            request_tracking.progress(tx, item)
            tx.put('items', item)
            return item

    async def execute(self, item):
        if not item:
            return
        response_received = False
        # Per execution, not shared by overlapping tasks. A cancelled OSS thread
        # can finish staging, but cannot call FAL after this coroutine is gone.
        phase = {'submit_entered': False}
        try:
            with self.db.transaction() as tx:
                current = tx.get('items', item['id'])
                if not current or current['status'] != 'running' or current.get('worker_id') != self.id or current.get('run_id') != item.get('run_id'):
                    return
                if current.get('cutout_inflight'):
                    raise ProviderFailure(CUTOUT_UNCERTAIN, 'unknown')
                order = tx.get('orders', item['order_id'])
                if not order_allowed(tx, order) and (current.get('processing_stage') == 'postprocess' or not current.get('fal_request_id')):
                    current.update(status='queued', remote_reserved=False)
                    tx.put('items', current)
                    return
                config = tx.get('config', 'settings')
                template = asset_bytes(self.db, tx.get('assets', item['template_id']))
                avatar = asset_bytes(self.db, tx.get('assets', item.get('avatar_id') or order['avatar_id']))
            if item.get('processing_stage') == 'postprocess':
                with self.db.transaction() as tx:
                    raw_asset = tx.get('assets', item.get('raw_result_id', ''))
                    if not raw_asset:
                        raise ProviderFailure('没有可恢复的原始生成结果')
                    data = asset_bytes(self.db, raw_asset)
                response_received = True
                processing_started = time.monotonic()
                image = decode(data, require_transparency=False)
            else:
                provider = self.provider or FalProvider(os.environ.get('FAL_KEY') or config.get('fal_api_key', ''), config.get('fal_upload_timeout', DEFAULT_UPLOAD_TIMEOUT))
                if hasattr(provider, 'submit'):
                    if not item.get('fal_request_id'):
                        job = await self.submit(provider, item, config, template, avatar, order['prompt'], phase)
                        if job is None:
                            return
                        self.checkpoint(item, **job)
                        return self.defer(item, 2)
                    if item.get('fal_status') != 'COMPLETED':
                        progress = await provider.poll(item)
                        if progress['fal_status'] != item.get('fal_status') or progress.get('queue_position') != item.get('queue_position'):
                            self.timing('fal_poll', item, status=progress['fal_status'], previous_status=item.get('fal_status'),
                                        queue_position=progress.get('queue_position'))
                        self.checkpoint(item, **progress)
                        item.update(progress)
                        if progress['fal_status'] != 'COMPLETED':
                            return self.defer(item, 2)
                    if item.get('fal_error'):
                        error = ProviderFailure(item['fal_error'], 'failed')
                        error.error_types = frozenset({item['fal_error_type']} if item.get('fal_error_type') else ())
                        raise error
                    download_started = time.monotonic()
                    downloaded = False
                    try:
                        data = await provider.result(item)
                        downloaded = True
                    finally:
                        self.timing('fal_result', item, outcome='success' if downloaded else 'error',
                                    download_ms=round((time.monotonic() - download_started) * 1000, 3))
                else:
                    phase['submit_entered'] = True
                    data = await provider.generate(template=template, avatar=avatar, prompt=order['prompt'])
                response_received = True
                processing_started = time.monotonic()
                image = decode(data, require_transparency=False)
                if image.size != (1024, 1024):
                    raise ProviderFailure('API图片尺寸不是约定的1024×1024，已拒绝发布')
                with self.db.transaction() as tx:
                    latest = tx.get('items', item['id'])
                    if latest['status'] != 'running' or latest.get('worker_id') != self.id or latest.get('run_id') != item.get('run_id'):
                        return
                    raw = save_asset(self.db, tx, encode(image), item['owner'], 'raw_result', order_id=item['order_id'])
                    latest.update(raw_result_id=raw['id'], remote_reserved=False, processing_stage='postprocess')
                    latest_order = tx.get('orders', item['order_id'])
                    if not order_allowed(tx, latest_order):
                        # Reconcile the already submitted generation, then pause before any new processing call.
                        latest.update(status='queued', next_at=0)
                        tx.put('items', latest)
                        return
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
                    latest_order = tx.get('orders', item['order_id'])
                    if not order_allowed(tx, latest_order):
                        latest.update(status='queued', next_at=0, remote_reserved=False, processing_stage='postprocess')
                        tx.put('items', latest)
                        return
                    latest.update(cutout_inflight=True, cutout_started_at=self.clock())
                    tx.put('items', latest)
                cutout = YeziProvider(self.db, key, self.clock)
                cutout.before_submit = lambda tx: self.cutout_allowed(tx, item)
                data = await cutout.cutout(data)
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
                from .customer_orders import reconcile
                reconcile(tx, order)
            self.timing('fal_postprocess_complete', item,
                        postprocess_ms=round((time.monotonic() - processing_started) * 1000, 3))
            await asyncio.to_thread(self.publish, item['order_id'])
        except asyncio.CancelledError:
            # Read the durable stage: execute's original claim may predate raw save.
            with self.db.transaction() as tx:
                latest = tx.get('items', item['id'])
            if not phase['submit_entered'] and latest and not latest.get('fal_request_id') and not latest.get('raw_result_id'):
                self.release_unsent(item)
            else:
                self.fail(item, ProviderFailure('请求执行时服务停止，保留原请求', 'retry' if latest.get('fal_request_id') or latest.get('raw_result_id') else 'unknown'))
            raise
        except CutoutDeferred:
            # The provider proves no request was sent, so the durable hold can safely become queued processing.
            with self.db.transaction() as tx:
                latest = tx.get('items', item['id'])
                if latest and latest['status'] == 'running' and latest.get('worker_id') == self.id and latest.get('run_id') == item.get('run_id'):
                    latest.pop('cutout_inflight', None)
                    latest.pop('cutout_started_at', None)
                    latest.update(status='queued', remote_reserved=False, processing_stage='postprocess', next_at=0)
                    tx.put('items', latest)
        except ProviderFailure as exc:
            if not self.retry_inline_after_download_error(item, exc):
                self.fail(item, exc)
        except Exception as exc:
            # Once a request starts, unexpected failures must not trigger another paid request.
            # Exception text may contain a provider's signed URL or payload.
            self.fail(item, ProviderFailure('结果处理失败：' + type(exc).__name__ + '；不会自动重新生图', 'failed' if response_received else 'unknown'))

    def retry_inline_after_download_error(self, item, error):
        """FAL could not fetch OSS inputs: the request ended without output or charge.

        Requeue once with inline images. Admission still applies when it is claimed
        again; customer retry counts and the order rerun budget are untouched.
        """
        if error.status != 'failed' or 'file_download_error' not in getattr(error, 'error_types', ()):
            return False
        with self.db.transaction() as tx:
            latest = tx.get('items', item['id'])
            if (not latest or latest['status'] != 'running' or latest.get('worker_id') != self.id or latest.get('run_id') != item.get('run_id')
                    or latest.get('fal_input') != 'oss' or latest.get('fal_force_inline') or latest.get('raw_result_id') or latest.get('cutout_inflight')):
                return False
            history = list(latest.get('fal_input_retries', []))
            history.append({'request_id': latest.get('fal_request_id'), 'reason': 'file_download_error', 'at': self.clock()})
            for field in ('fal_request_id', 'fal_status', 'fal_status_url', 'fal_response_url', 'fal_error', 'fal_error_type', 'queue_position'):
                latest.pop(field, None)
            latest.update(status='queued', remote_reserved=False, next_at=0, error=None,
                          fal_force_inline=True, fal_input_retries=history)
            tx.put('items', latest)
        self.timing('fal_input_retry', item, reason='file_download_error', previous_request_id=history[-1]['request_id'])
        return True

    def timing(self, event, item, **fields):
        timing_log.info(json.dumps(dict(event=event, item_id=item['id'], at=self.clock(), **fields),
                            ensure_ascii=False, separators=(',', ':')))

    async def submit(self, provider, item, config, template, avatar, prompt, phase):
        """Stage before POST; failures fall back within this same paid attempt."""
        mode, reason, image_urls = 'inline', None, None
        stage_ms, reused = 0, []
        if item.get('fal_force_inline'):
            # One automatic resubmission after FAL failed to fetch the OSS inputs.
            mode, reason = 'fallback', 'fal_download_retry'
        elif config.get('fal_input_mode', 'inline') == 'oss':
            stage_started = time.monotonic()
            try:
                store = oss_delivery.create_store()
                if store is None:
                    reason = 'oss_not_configured'
                else:
                    ttl = int(os.environ.get('STUDIO_FAL_INPUT_URL_TTL', '7200'))
                    if ttl <= 0:
                        raise ValueError('Invalid input TTL')
                    urls = []
                    for data in (template, avatar):
                        stats = {}
                        key = await asyncio.to_thread(oss_delivery.stage_fal_input, store, data, stats=stats)
                        reused.append(stats['reused'])
                        urls.append(await asyncio.to_thread(store.sign_input, key, ttl))
                    image_urls, mode = urls, 'oss'
            except Exception:
                # Do not stringify SDK exceptions: they can contain credentials.
                reason = 'oss_stage_failed'
            finally:
                stage_ms = round((time.monotonic() - stage_started) * 1000, 3)
            if reason:
                mode = 'fallback'
        actual = 'oss' if image_urls is not None else 'inline'
        # All awaitable preparation has finished. Recheck the live claim and
        # policy transactionally, then enter submit without another await gap.
        if not self.admit_submission(item, fal_input=actual, fal_input_fallback_reason=reason):
            return None
        started, metrics, outcome = time.monotonic(), {}, 'success'
        try:
            kwargs = {'image_urls': image_urls} if image_urls is not None else {}
            phase['submit_entered'] = True
            job = await provider.submit(template=template, avatar=avatar, prompt=prompt, **kwargs)
            metrics = job.get('fal_submit_metrics', {})
            job['fal_input'] = actual
            return job
        except BaseException as exc:
            metrics = getattr(exc, 'submit_metrics', {})
            outcome = exc.status if isinstance(exc, ProviderFailure) else 'error'
            raise
        finally:
            self.timing('fal_submit', item, mode=mode, fallback_reason=reason, objects_reused=reused,
                        stage_ms=stage_ms, post_ms=metrics.get('post_ms', round((time.monotonic() - started) * 1000, 3)),
                        request_bytes=metrics.get('request_bytes'), outcome=outcome)

    def unpublished(self):
        with self.db.transaction(readonly=True) as tx:
            return [o['id'] for o in tx.where('orders', 'state', 'submitted')
                    if not o.get('processing_error') and (not o.get('delivery_ready') or not o.get('overview_ready'))]

    def cutout_allowed(self, tx, item):
        latest = tx.get('items', item['id'])
        order = tx.get('orders', item['order_id'])
        return bool(latest and order and order_allowed(tx, order) and latest['status'] == 'running' and
                    latest.get('worker_id') == self.id and latest.get('run_id') == item.get('run_id'))

    def checkpoint(self, item, **fields):
        with self.db.transaction() as tx:
            latest = tx.get('items', item['id'])
            if latest and latest['status']=='running' and latest.get('run_id') == item.get('run_id') and latest.get('worker_id') == self.id:
                latest.update(fields)
                request_tracking.progress(tx, latest)
                tx.put('items', latest)
                return True
            return False

    def release_unsent(self, item):
        return self.checkpoint(item, status='queued', remote_reserved=False, next_at=0)

    def admit_submission(self, item, **fields):
        """No network IO here; stale executions must not overwrite a new owner."""
        with self.db.transaction() as tx:
            latest = tx.get('items', item['id'])
            if not latest or latest['status'] != 'running' or latest.get('run_id') != item.get('run_id') or latest.get('worker_id') != self.id:
                return False
            if latest.get('fal_request_id') or latest.get('raw_result_id'):
                return False
            order = tx.get('orders', latest['order_id'])
            owner = tx.get('users', latest['owner'])
            org = tx.get('organizations', order['organization_id']) if order else None
            allowed = bool(order_allowed(tx, order) and not order.get('paused') and owner and owner.get('active')
                           and owner.get('organization_id') == order.get('organization_id') and org and org.get('active'))
            latest.update(fields)
            if not allowed:
                latest.update(status='queued', remote_reserved=False, next_at=0)
            request_tracking.progress(tx, latest)
            tx.put('items', latest)
            return allowed

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
            request_tracking.progress(tx, latest)
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
                from .customer_orders import reconcile
                reconcile(tx, order)
            from .publication import publish_customer
            return publish_customer(self.db, order, force, watermark_only)
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

    async def sync_oss(self):
        try:
            await asyncio.to_thread(oss_delivery.sync, self.db)
        except Exception:
            # SDK exception text may contain credentials or signed URLs.
            log.warning('OSS scheduling failed; will retry')

    async def run(self):
        while not self.stopping:
            try:
                self.heartbeat()
                await asyncio.to_thread(self.recover)
                # Startup or racing publishers may have saved images but not their derived files.
                pending = await asyncio.to_thread(self.unpublished)
                # Hook (seller remark lookup) that must finish before an order's pages are laid out.
                if pending and self.before_publish:
                    await asyncio.gather(*(self.before_publish(id) for id in pending))
                for id in pending:
                    await asyncio.to_thread(self.publish, id)
                tick = self.clock()
                if not self.stopping and tick >= self.oss_next_sync:
                    self.oss_next_sync = tick + 30
                    if self.oss_task is None or self.oss_task.done():
                        # A backlog or timeout must not delay generation admission.
                        self.oss_task = asyncio.create_task(self.sync_oss())
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
        if self.oss_task:
            self.oss_task.cancel()
            await asyncio.gather(self.oss_task, return_exceptions=True)
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
