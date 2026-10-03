"""Persistent disk cache for watermarked customer media, retention sweeps and background pregeneration.

Layout under the cache root (STUDIO_MEDIA_CACHE_DIR, default <data>/media-cache):
  library/<asset_id>/<mark>-<size>-<pipeline>.webp            active library stickers, for watermarks still in use
  customer/<org_id>/<asset_id>/<mark>-<size>-<pipeline>.webp  avatars/results/overviews, deleted N days after last use
File names are content keys (watermark text digest, tier, render pipeline), so a changed watermark or
pipeline is simply a different file and is never served stale. There is no size limit; writes are only
skipped while free disk space is below MIN_FREE_BYTES so the database keeps room to grow.
"""
import hashlib
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

DEFAULT_RETENTION_DAYS = 15
MIN_FREE_BYTES = 512 * 1024 * 1024
LIBRARY_TIERS = (160, 320, 640)
CUSTOMER_TIER = 640
# Last-use refreshes are throttled so hot files are not re-stamped on every hit.
TOUCH_AFTER = 3600
_ID = re.compile('[0-9a-f]{32}')
_NAME = re.compile(r'([0-9a-f]{16})-(\d+)-([0-9a-f]{8})\.webp')


def mark_digest(mark):
    return hashlib.sha256(mark.encode()).hexdigest()[:16]


def pipeline_digest(pipeline, already_watermarked):
    return hashlib.sha256(f'{pipeline}:{bool(already_watermarked)}'.encode()).hexdigest()[:8]


def watermark_of(user):
    # Same rule as order creation: blank watermark falls back to the account display name.
    return user.get('watermark', '').strip() or user['display_name']


def retention_days(organization):
    return int((organization or {}).get('media_cache_days') or DEFAULT_RETENTION_DAYS)


def library_owner(tx, organization_id, asset_id):
    """Indexed lookup: is asset_id the image of an active sticker in this organization?"""
    return any(s.get('active') and not s.get('deleted') and s.get('organization_id') == organization_id
               for s in tx.find('stickers', ("json_extract(doc,'$.image.id') = ?", (asset_id,))))


class MediaCache:
    def __init__(self, db, root=None):
        self.db = db
        self.root = Path(root or os.environ.get('STUDIO_MEDIA_CACHE_DIR') or db.root / 'media-cache')

    def path(self, scope, organization_id, asset_id, mark, size, pipeline, already_watermarked=False):
        if not _ID.fullmatch(asset_id) or scope not in {'library', 'customer'}:
            return None
        base = self.root / 'library' if scope == 'library' else self.root / 'customer' / organization_id
        return base / asset_id / f'{mark_digest(mark)}-{size}-{pipeline_digest(pipeline, already_watermarked)}.webp'

    def read(self, path):
        if path is None:
            return None
        try:
            if path.is_symlink():
                return None
            data = path.read_bytes()
            if time.time() - path.stat().st_mtime > TOUCH_AFTER:
                os.utime(path)
            return data or None
        except OSError:
            return None

    def refresh(self, path, data):
        """After a memory hit: keep the disk copy present and its last-use time current (throttled)."""
        if path is None:
            return
        try:
            if time.time() - path.stat().st_mtime > TOUCH_AFTER:
                os.utime(path)
        except FileNotFoundError:
            self.write(path, data)
        except OSError:
            pass

    def write(self, path, data):
        """Atomic, best-effort: a failed or skipped write never fails the request."""
        if path is None:
            return False
        temporary = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
        try:
            if shutil.disk_usage(self.root if self.root.exists() else self.db.root).free < MIN_FREE_BYTES + len(data):
                return False
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with temporary.open('xb') as handle:
                handle.write(data)
            os.replace(temporary, path)
            return True
        except OSError:
            return False
        finally:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass

    def exists(self, path):
        return path is not None and path.is_file() and not path.is_symlink()

    def _asset_dirs(self, asset_id):
        if self.root.is_symlink():
            return []
        dirs = [self.root / 'library' / asset_id]
        customer = self.root / 'customer'
        if customer.is_dir() and not customer.is_symlink():
            dirs += [org / asset_id for org in customer.iterdir() if org.is_dir() and not org.is_symlink()]
        return dirs

    def files_for(self, asset_ids):
        files = []
        for asset_id in asset_ids:
            for directory in self._asset_dirs(asset_id):
                if directory.is_dir() and not directory.is_symlink():
                    files += [p for p in directory.iterdir() if p.is_file() and not p.is_symlink()]
        return files

    def remove_asset(self, asset_id):
        """Called by durable cleanup when an asset is deleted; never follows symlinks."""
        if not _ID.fullmatch(asset_id):
            raise OSError('无效的缓存编号')
        for directory in self._asset_dirs(asset_id):
            if directory.is_symlink():
                raise OSError('不允许清理缓存符号链接')
            if directory.is_dir():
                shutil.rmtree(directory)

    def _walk(self, scope):
        base = self.root / scope
        if self.root.is_symlink() or not base.is_dir() or base.is_symlink():
            return
        for current, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if not (Path(current) / d).is_symlink()]
            for name in names:
                yield Path(current) / name

    def stats(self):
        result = {}
        for scope in ('library', 'customer'):
            files = size = 0
            for path in self._walk(scope):
                try:
                    size += path.stat().st_size
                    files += 1
                except OSError:
                    pass
            result[scope] = {'files': files, 'bytes': size}
        return result

    def sweep(self, now=None):
        """Retention and orphan removal. Inputs are read in one snapshot; file IO happens outside it."""
        now = now or time.time()
        with self.db.transaction(readonly=True) as tx:
            organizations = {o['id']: o for o in tx.all('organizations')}
            assets = {a['id']: a.get('organization_id') for a in tx.all('assets')}
            library = {s['image']['id']: s.get('organization_id') for s in tx.all('stickers')
                       if s.get('active') and not s.get('deleted')}
            marks = marks_in_use(tx)
        removed = 0
        current = {pipeline_digest(_pipeline(size), False) for size in LIBRARY_TIERS}
        for path in list(self._walk('library')):
            match = _NAME.fullmatch(path.name)
            organization_id = library.get(path.parent.name)
            if (organization_id is None or not match or match.group(3) not in current
                    or match.group(1) not in {mark_digest(m) for m in marks.get(organization_id, ())}):
                removed += _unlink(path)
        for path in list(self._walk('customer')):
            organization_id, asset_id = path.parent.parent.name, path.parent.name
            limit = retention_days(organizations.get(organization_id)) * 86400
            try:
                stale = now - path.stat().st_mtime > limit
            except OSError:
                continue
            if stale or asset_id not in assets or path.name.endswith('.tmp'):
                removed += _unlink(path)
        for scope in ('library', 'customer'):
            base = self.root / scope
            if base.is_dir() and not base.is_symlink():
                for current_dir, dirs, _ in os.walk(base, topdown=False):
                    for name in dirs:
                        try: (Path(current_dir) / name).rmdir()
                        except OSError: pass
        return removed


def _pipeline(size):
    from .guest_media import pipeline
    return pipeline(size)


def _unlink(path):
    try:
        path.unlink()
        return 1
    except OSError:
        return 0


def marks_in_use(tx):
    """Watermark texts customers can currently see per organization: every active member's
    watermark (new orders copy it) plus the snapshot watermark of every open order."""
    result = {}
    for member in tx.all('users'):
        if member.get('active') and member.get('organization_id'):
            result.setdefault(member['organization_id'], set()).add(watermark_of(member))
    for order in tx.where('orders', 'workflow_version', 3):
        if order.get('state') in {'draft', 'review'} and order.get('organization_id'):
            result.setdefault(order['organization_id'], set()).add(order['watermark'])
    return result


class MediaWarmer:
    """Background pregeneration at the lowest CPU priority, plus periodic retention sweeps.

    Library: tiers 160/320/640 of every active sticker for every watermark in use, rendered
    from one 640 watermark pass. Customer: the 640 preview of avatars/results of open orders
    (and ready overviews) whose original is newer than the organization's retention window,
    so expired files are not immediately recreated.
    """

    def __init__(self, db, cache, interval=600, pause=0.02):
        self.db, self.cache, self.interval, self.pause = db, cache, interval, pause
        self._stop = threading.Event()
        self._thread = None
        self.status = {'running': False, 'last_started': None, 'last_finished': None,
                       'generated': 0, 'pending': None, 'removed': 0, 'errors': 0}

    def start(self):
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='media-warmer', daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None

    def _loop(self):
        if sys.platform.startswith('linux'):
            # Linux applies nice per thread: renders here yield the CPU to customer requests.
            try:
                os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
            except OSError:
                pass
        # Let startup and the first requests go first.
        if self._stop.wait(30):
            return
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                self.status['errors'] += 1
            self._stop.wait(self.interval)

    def targets(self, now=None):
        now = now or time.time()
        from .guest_media import pipeline
        jobs = []
        with self.db.transaction(readonly=True) as tx:
            marks = marks_in_use(tx)
            stickers = [s for s in tx.all('stickers') if s.get('active') and not s.get('deleted')]
            for sticker in stickers:
                for mark in sorted(marks.get(sticker.get('organization_id'), ())):
                    paths = {size: self.cache.path('library', None, sticker['image']['id'], mark, size, pipeline(size)) for size in LIBRARY_TIERS}
                    if not all(self.cache.exists(p) for p in paths.values()):
                        jobs.append(('library', sticker['image']['id'], mark, paths, False))
            organizations = {o['id']: o for o in tx.all('organizations')}
            for order in tx.where('orders', 'workflow_version', 3):
                organization_id = order.get('organization_id')
                if not organization_id:
                    continue
                window = retention_days(organizations.get(organization_id)) * 86400
                wanted = []
                if order.get('state') in {'draft', 'review'}:
                    wanted += [(a['asset_id'], False) for a in order.get('avatars', [])]
                    wanted += [(v['asset_id'], False) for s in order.get('slots', []) for v in s.get('versions', [])]
                if order.get('state') != 'cancelled' and order.get('overview_ready') and order.get('overview_id'):
                    wanted.append((order['overview_id'], order.get('overview_style') == 'guest-overview-v1'))
                for asset_id, already in wanted:
                    asset = tx.get('assets', asset_id or '')
                    if not asset:
                        continue
                    try:
                        if now - (self.db.root / 'assets' / asset['file']).stat().st_mtime > window:
                            continue
                    except OSError:
                        continue
                    path = self.cache.path('customer', organization_id, asset_id, order['watermark'], CUSTOMER_TIER, pipeline(CUSTOMER_TIER), already)
                    if path is not None and not self.cache.exists(path):
                        jobs.append(('customer', asset_id, order['watermark'], {CUSTOMER_TIER: path}, already))
        return jobs

    def run_once(self, now=None):
        from .guest_media import render_tiers
        from .storage import asset_bytes
        self.status.update(running=True, last_started=time.time())
        try:
            self.status['removed'] += self.cache.sweep(now)
            jobs = self.targets(now)
            self.status['pending'] = len(jobs)
            for scope, asset_id, mark, paths, already in jobs:
                if self._stop.is_set():
                    break
                missing = {size: path for size, path in paths.items() if not self.cache.exists(path)}
                if missing:
                    try:
                        with self.db.transaction(readonly=True) as tx:
                            asset = tx.get('assets', asset_id)
                        data = asset_bytes(self.db, asset)
                        for size, rendered in render_tiers(data, mark, tuple(missing), already).items():
                            self.status['generated'] += self.cache.write(missing[size], rendered)
                    except Exception:
                        self.status['errors'] += 1
                self.status['pending'] -= 1
                if self.pause:
                    time.sleep(self.pause)
        finally:
            self.status.update(running=False, last_finished=time.time())
