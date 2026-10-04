"""Optional private OSS delivery; orders remain the sole synchronization state.

Only ECS instance-role credentials are supported. Never log SDK exceptions: their
text can contain signed URLs, security tokens, or upstream request bodies.
"""
import hashlib
import logging
import os
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from .storage import asset_bytes

log = logging.getLogger(__name__)
# asyncio cancellation does not stop a to_thread call. This process-wide lock
# also covers a replacement Worker while its predecessor's IO is completing.
_sync_lock = threading.Lock()
_cleanup_times = weakref.WeakKeyDictionary()
# Only active keys are retained. A small registry lock protects reference counts;
# remote IO uses a separate lock per key, never the print synchronization lock.
_input_locks_guard = threading.Lock()
_input_locks = {}


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int = 0
    last_modified: object = None
    metadata: dict = field(default_factory=dict)


class OSSStore:
    """Small SDK adapter shared by print delivery and manual backup archival."""
    def __init__(self, bucket, internal, public, ttl):
        self.bucket, self.internal, self.public, self.ttl = bucket, internal, public, ttl

    def upload(self, key, body, *, content_type='application/octet-stream', metadata=None,
               cache_control='private, no-store'):
        import alibabacloud_oss_v2 as oss
        self.internal.put_object(oss.PutObjectRequest(bucket=self.bucket, key=key, body=body,
            content_type=content_type, cache_control=cache_control, metadata=metadata))

    def list(self, prefix):
        import alibabacloud_oss_v2 as oss
        token = None
        while True:
            result = self.internal.list_objects_v2(oss.ListObjectsV2Request(
                bucket=self.bucket, prefix=prefix, continuation_token=token, max_keys=1000))
            for item in result.contents or []:
                yield ObjectInfo(item.key, item.size, item.last_modified)
            if not result.is_truncated:
                return
            token = result.next_continuation_token
            if not token:
                raise ValueError('Missing continuation token')

    def head(self, key):
        import alibabacloud_oss_v2 as oss
        result = self.internal.head_object(oss.HeadObjectRequest(bucket=self.bucket, key=key))
        return ObjectInfo(key, result.content_length, result.last_modified, result.metadata or {})

    @contextmanager
    def read(self, key):
        import alibabacloud_oss_v2 as oss
        result = self.internal.get_object(oss.GetObjectRequest(bucket=self.bucket, key=key))
        try:
            yield result.body
        finally:
            result.body.close()

    def delete(self, key):
        import alibabacloud_oss_v2 as oss
        self.internal.delete_object(oss.DeleteObjectRequest(bucket=self.bucket, key=key))

    def sign(self, key):
        import alibabacloud_oss_v2 as oss
        return self.public.presign(oss.GetObjectRequest(bucket=self.bucket, key=key,
            response_content_disposition='attachment'), expires=timedelta(seconds=self.ttl)).url

    def sign_input(self, key, ttl):
        import alibabacloud_oss_v2 as oss
        return self.public.presign(oss.GetObjectRequest(bucket=self.bucket, key=key),
            expires=timedelta(seconds=ttl)).url


@contextmanager
def _input_lock(store, key):
    identity = (store.bucket, key)
    with _input_locks_guard:
        entry = _input_locks.setdefault(identity, [threading.Lock(), 0])
        entry[1] += 1
    try:
        with entry[0]:
            yield
    finally:
        with _input_locks_guard:
            entry[1] -= 1
            if not entry[1]:
                del _input_locks[identity]


def stage_fal_input(store, data, *, stats=None):
    """Content-addressed daily input; only a proven absent object permits PUT.

    IO runs outside database transactions. Same-key concurrent submissions share
    a HEAD/PUT lock; distinct images proceed independently. No URL is retained.
    """
    from alibabacloud_oss_v2.exceptions import OperationError, ServiceError
    key = f"fal-inputs/{datetime.now(timezone.utc):%Y%m%d}/{hashlib.sha256(data).hexdigest()}.png"
    with _input_lock(store, key):
        reused = True
        try:
            store.head(key)
        except (OperationError, ServiceError) as exc:
            # SDK calls wrap service failures in OperationError. Unwrap only
            # that documented type, never exception text or arbitrary causes.
            failure = exc
            for _ in range(8):
                if not isinstance(failure, OperationError):
                    break
                failure = failure.unwrap()
            if not isinstance(failure, ServiceError) or failure.status_code != 404 or failure.code != 'NoSuchKey':
                raise
            store.upload(key, data, content_type='image/png')
            reused = False
        if stats is not None:
            stats['reused'] = reused
    return key


@lru_cache(maxsize=4)
def _configured_store(bucket, region, internal_endpoint, public_endpoint, role, ttl):
    import alibabacloud_oss_v2 as oss
    from alibabacloud_credentials.client import Client as CredentialsClient
    from alibabacloud_credentials.models import Config as CredentialsConfig
    # Explicit type bypasses the SDK's environment/static-key default chain.
    credentials = CredentialsClient(CredentialsConfig(type='ecs_ram_role', role_name=role,
        disable_imds_v1=True, timeout=3000, connect_timeout=3000))
    def get_credentials():
        credential = credentials.get_credential()
        return oss.credentials.Credentials(credential.access_key_id, credential.access_key_secret,
                                           credential.security_token)
    provider = oss.credentials.CredentialsProviderFunc(get_credentials)
    def client(endpoint):
        return oss.Client(oss.Config(region=region, endpoint=endpoint, credentials_provider=provider,
            connect_timeout=5, readwrite_timeout=30, retry_max_attempts=3))
    return OSSStore(bucket, client(internal_endpoint), client(public_endpoint), ttl)


def create_store():
    """Construct without external IO; an empty bucket disables the integration."""
    bucket = os.environ.get('STUDIO_OSS_BUCKET', '').strip()
    if not bucket:
        return None
    return _configured_store(bucket, os.environ.get('STUDIO_OSS_REGION', 'cn-wulanchabu'),
        os.environ.get('STUDIO_OSS_INTERNAL_ENDPOINT', 'oss-cn-wulanchabu-internal.aliyuncs.com'),
        os.environ.get('STUDIO_OSS_PUBLIC_ENDPOINT', 'oss-cn-wulanchabu.aliyuncs.com'),
        os.environ.get('STUDIO_OSS_RAM_ROLE', 'sticker-ecs-oss'),
        int(os.environ.get('STUDIO_OSS_URL_TTL', '300')))


def expected_key(order, artifact):
    return f"print/{order['organization_id']}/{order['id']}/{artifact['sha256']}.png"


def active(order):
    return bool(order and order.get('state') == 'submitted' and order.get('delivery_ready'))


def sign(key):
    """Call only after complete staff/order authorization; failure falls back locally."""
    if os.environ.get('STUDIO_OSS_DOWNLOAD', '1') == '0':
        return None
    try:
        store = create_store()
        return store.sign(key) if store else None
    except Exception:
        log.warning('OSS download signing failed; local delivery remains available')
        return None


def _active_keys(tx):
    return {expected_key(order, artifact) for order in tx.where('orders', 'state', 'submitted')
            if active(order) for artifact in order.get('artifacts', []) if artifact.get('kind') == 'print'}


def _cleanup(db, store):
    for remote in store.list('print/'):
        # Re-read after remote listing, immediately before delete. Expected keys
        # protect same-hash republishing even before oss_key has been written.
        try:
            with db.transaction() as tx:
                if remote.key in _active_keys(tx):
                    continue
                # Clear before deletion: a lost delete response or process exit
                # must not leave a permanent marker for an absent remote object.
                # Cancellation retains artifacts; restoration will reupload.
                for order in tx.all('orders'):
                    changed = False
                    for artifact in order.get('artifacts', []):
                        if artifact.get('oss_key') == remote.key:
                            artifact.pop('oss_key')
                            changed = True
                    if changed:
                        tx.put('orders', order)
            store.delete(remote.key)
        except Exception:
            log.warning('OSS obsolete print cleanup failed; will retry')


def sync(db, *, now=None):
    """Serial upload and ten-minute reconciliation; no IO holds a DB transaction."""
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        store = create_store()
        if store is None:
            return
        with db.transaction(readonly=True) as tx:
            pending = [(order, artifact, tx.get('assets', artifact['id']))
                for order in tx.where('orders', 'state', 'submitted') if active(order)
                for artifact in order.get('artifacts', []) if artifact.get('kind') == 'print'
                and artifact.get('oss_key') != expected_key(order, artifact)]
        for order, artifact, asset in pending:
            try:
                data = asset_bytes(db, asset)
                if hashlib.sha256(data).hexdigest() != artifact['sha256']:
                    raise ValueError('Local print hash mismatch')
                key = expected_key(order, artifact)
                store.upload(key, data, content_type='image/png', cache_control='private, no-store')
                with db.transaction() as tx:
                    current = tx.get('orders', order['id'])
                    if not active(current):
                        continue
                    for current_artifact in current.get('artifacts', []):
                        if (current_artifact.get('kind') == 'print' and current_artifact['id'] == artifact['id']
                            and current_artifact['sha256'] == artifact['sha256']
                            and expected_key(current, current_artifact) == key):
                            current_artifact['oss_key'] = key
                            tx.put('orders', current)
                            break
            except Exception:
                log.warning('OSS print upload failed; will retry')
        tick = time.monotonic() if now is None else now
        last = _cleanup_times.get(db)
        if last is None or tick - last >= 600:
            _cleanup(db, store)
            _cleanup_times[db] = tick
    except Exception:
        log.warning('OSS synchronization failed; will retry')
    finally:
        _sync_lock.release()
