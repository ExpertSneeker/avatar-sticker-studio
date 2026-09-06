"""Disposable, private WebP derivatives. Originals are never modified.

One encoder per data directory, across threads/processes. Do not acquire this
lock while holding a database transaction: cleanup also needs the database.
"""
import fcntl
import hashlib
import io
import os
import re
import shutil
import threading
from contextlib import contextmanager

from fastapi import HTTPException
from PIL import Image

CACHE_LIMIT = 256 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
PIPELINE = 'webp-q80-m4-v1'
_thread_lock = threading.Lock()


@contextmanager
def cache_lock(db):
    with _thread_lock:
        with (db.root / '.preview-cache.lock').open('a') as handle:
            os.chmod(handle.name, 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def cached_files(db, asset_ids=None):
    root = db.root / 'preview-cache'
    if root.is_symlink():
        return []
    dirs = (root / id for id in asset_ids) if asset_ids is not None else root.glob('*')
    files = []
    for directory in dirs:
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            files.extend(p for p in directory.iterdir() if not p.is_symlink() and p.is_file())
        except FileNotFoundError:
            # Storage/cleanup previews do not hold the encoder lock; LRU may prune
            # this directory between the existence check and enumeration.
            continue
    return files


def remove_asset_cache(db, id):
    """Called under cache_lock by durable cleanup; never follow symlinks."""
    root = db.root / 'preview-cache'
    directory = root / id
    if root.is_symlink() or directory.is_symlink():
        raise OSError('不允许清理缓存符号链接')
    if directory.exists():
        for path in directory.iterdir():
            path.unlink(missing_ok=True)
        directory.rmdir()


class PreviewCache:
    def __init__(self, db):
        self.db = db
        self.root = db.root / 'preview-cache'
        self.max_bytes = CACHE_LIMIT

    def etag(self, asset, size):
        digest = hashlib.sha256(f"{asset['id']}:{asset['sha256']}:{size}:{PIPELINE}".encode()).hexdigest()
        return f'W/"{digest}"'

    def _encode(self, asset, size):
        try:
            with Image.open(self.db.root / 'assets' / asset['file']) as image:
                image.thumbnail((size, size), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, 'WEBP', quality=80, method=4)
                return output.getvalue()
        except FileNotFoundError as exc:
            raise HTTPException(404, '文件不存在') from exc
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(422, '图片无法生成预览，请检查原始文件') from exc

    def _prune(self, incoming=0):
        entries = []
        for path in cached_files(self.db):
            try:
                if path.suffix == '.tmp':
                    path.unlink()
                    continue
                stat = path.stat()
                entries.append((stat.st_mtime_ns, path, stat.st_size))
            except FileNotFoundError:
                pass
        total = sum(entry[2] for entry in entries)
        # Hysteresis avoids rescanning/evicting a single file at every full-cache miss.
        target = max(0, int(self.max_bytes * .8) - incoming) if total + incoming > self.max_bytes else self.max_bytes - incoming
        for _, path, size in sorted(entries):
            if total <= target:
                break
            path.unlink(missing_ok=True)
            total -= size
        # Empty per-asset directories must not accumulate after LRU eviction.
        if self.root.exists():
            for directory in self.root.iterdir():
                if directory.is_dir() and not directory.is_symlink():
                    try: directory.rmdir()
                    except OSError: pass
        return total

    def get(self, asset, size):
        if size not in (320, 1280) or not re.fullmatch('[0-9a-f]{32}', asset['id']):
            raise HTTPException(422, '不支持的预览尺寸或文件编号')
        with cache_lock(self.db):
            # Cleanup may have committed while this request waited for the encoder.
            with self.db.transaction() as tx:
                if not tx.get('assets', asset['id']):
                    raise HTTPException(404, '文件不存在')
            directory = self.root / asset['id']
            if self.root.is_symlink() or directory.is_symlink():
                raise HTTPException(503, '预览缓存目录不可用')
            path = directory / (self.etag(asset, size)[3:-1] + '.webp')
            try:
                if path.is_symlink():
                    raise HTTPException(503, '预览缓存文件不可用')
                data = path.read_bytes()
                path.touch()
                return data
            except FileNotFoundError:
                pass
            data = self._encode(asset, size)
            with self.db.transaction() as tx:
                if not tx.get('assets', asset['id']):
                    raise HTTPException(404, '文件不存在')
            # Low disk / read-only disk never switches the client to the large original.
            # Encode once for this response, without persisting a derivative.
            temporary = path.with_suffix('.tmp')
            try:
                self._prune(len(data))
                if len(data) > self.max_bytes or shutil.disk_usage(self.db.root).free < MIN_FREE_BYTES + len(data):
                    return data
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(self.root, 0o700)
                with temporary.open('xb') as handle:
                    os.chmod(temporary, 0o600)
                    handle.write(data)
                os.replace(temporary, path)
            except OSError:
                pass
            finally:
                try: temporary.unlink(missing_ok=True)
                except OSError: pass
            return data
