#!/usr/bin/env python3
"""Manually archive immutable release backups to OSS; pruning is dry-run by default.

Run with the release venv and production OSS environment. No Database is opened.
The timestamp identifies the source directory's creation snapshot (mtime after
backup completion), never the upload date. Verified sidecars are written only
after a complete streamed readback; unknown local/remote entries are untouched.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_ROOT = Path('/opt/avatar-sticker-studio/backups')
NAME = r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}'
KEY = re.compile(r'backups/(?P<stamp>\d{8}T\d{6}Z)-(?P<name>' + NAME + r')\.tar\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
FORMAT = 'sticker-backup-v1'
CHUNK = 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def _hash(stream):
    digest, size = hashlib.sha256(), 0
    while chunk := stream.read(CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _root(root):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('backup root must be an existing real directory')
    return root.resolve()


@contextmanager
def _lock(root):
    # Serialize this tool's archive/prune runs; do not alter backup directory mtimes.
    descriptor = os.open(root / '.backup-archive.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _tree(path):
    entries = []
    def visit(current):
        info = current.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError('backup contains a symlink or special file')
        entries.append((current, [str(current.relative_to(path.parent)), info.st_mode, info.st_size,
                                  info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev]))
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(current.iterdir()):
                visit(child)
    visit(path)
    return entries


def _snapshot(path, root):
    path = Path(path).absolute()
    if path.is_symlink() or path.parent.resolve() != root or not re.fullmatch(NAME, path.name):
        raise ValueError('backup must be a named direct child of backup root')
    if not path.is_dir() or not (path / 'data' / 'studio.sqlite3').is_file():
        raise ValueError('backup lacks data/studio.sqlite3')
    entries = _tree(path)
    fingerprint = hashlib.sha256(_json([entry[1] for entry in entries])).hexdigest()
    created = int(path.stat().st_mtime)
    stamp = datetime.fromtimestamp(created, timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return {'name': path.name, 'timestamp': created, 'key': f'backups/{stamp}-{path.name}.tar',
            'fingerprint': fingerprint, 'path': path, 'entries': entries}


def _remote(store, value):
    """Only archives issued by this tool are eligible for automatic retention."""
    match = KEY.fullmatch(value.key)
    if not match:
        return None
    info = store.head(value.key)  # ListObjects does not include user metadata.
    metadata = info.metadata or {}
    try:
        created = int(datetime.strptime(match['stamp'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None
    if (metadata.get('archive-format') != FORMAT or metadata.get('snapshot-name') != match['name'] or
            metadata.get('snapshot-created') != str(created) or not SHA256.fullmatch(metadata.get('sha256', '')) or
            not SHA256.fullmatch(metadata.get('source-fingerprint', ''))):
        return None
    return {'name': match['name'], 'timestamp': created, 'key': value.key, 'info': info}


def _verified(store, remote, listed_keys, fingerprint=None):
    key, info = remote['key'], remote['info']
    marker = key + '.verified.json'
    if marker not in listed_keys:
        return False
    with store.read(marker) as stream:
        raw = stream.read(16_385)
    if len(raw) > 16_384:
        return False
    try:
        proof = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return False
    metadata = info.metadata or {}
    return bool(isinstance(proof, dict) and proof.get('format') == FORMAT and proof.get('key') == key and
                proof.get('sha256') == metadata.get('sha256') and proof.get('size') == info.size and
                proof.get('source_fingerprint') == metadata.get('source-fingerprint') and
                (fingerprint is None or proof.get('source_fingerprint') == fingerprint))


def archive_snapshot(path, store, *, backups_root=DEFAULT_ROOT, temp_dir='/var/tmp', verify_readback=False):
    root = _root(backups_root)
    with _lock(root):
        source = _snapshot(path, root)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='sticker-backup-', suffix='.tar', dir=temp_dir, delete=False) as handle:
                temporary = Path(handle.name)
            with tarfile.open(temporary, 'w', format=tarfile.PAX_FORMAT) as archive:
                for entry, _ in source['entries']:
                    info = archive.gettarinfo(str(entry), arcname=str(entry.relative_to(root)))
                    # Do not follow links, including a path replaced since the preflight.
                    if not (info.isfile() or info.isdir()):
                        raise ValueError('backup contains a link or special file')
                    if info.isfile():
                        descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
                        with os.fdopen(descriptor, 'rb') as payload:
                            archive.addfile(info, payload)
                    else:
                        archive.addfile(info)
            if _snapshot(path, root)['fingerprint'] != source['fingerprint']:
                raise ValueError('backup changed while archiving')
            with temporary.open('rb') as payload:
                sha256, size = _hash(payload)
            metadata = {'archive-format': FORMAT, 'sha256': sha256, 'snapshot-name': source['name'],
                        'snapshot-created': str(source['timestamp']), 'source-fingerprint': source['fingerprint']}
            listed = {value.key: value for value in store.list('backups/')}
            key = source['key']
            if key in listed:
                existing = store.head(key)
                if existing.size != size or existing.metadata != metadata:
                    raise ValueError('existing archive differs; refusing to overwrite a snapshot')
            else:
                with temporary.open('rb') as payload:
                    store.upload(key, payload, content_type='application/x-tar', metadata=metadata)
            remote = {'key': key, 'info': store.head(key)}
            verified = _verified(store, remote, listed, source['fingerprint'])
            if verify_readback:
                with store.read(key) as payload:
                    downloaded_sha, downloaded_size = _hash(payload)
                if (downloaded_sha, downloaded_size) != (sha256, size):
                    # Invalidate an older proof if a later integrity check detects corruption.
                    marker = key + '.verified.json'
                    if marker in listed:
                        store.delete(marker)
                    raise ValueError('archive readback hash or size mismatch')
                proof = {'format': FORMAT, 'key': key, 'sha256': sha256, 'size': size,
                         'source_fingerprint': source['fingerprint'],
                         'verified_at': datetime.now(timezone.utc).isoformat()}
                store.upload(key + '.verified.json', _json(proof), content_type='application/json')
                verified = True
            return {'name': source['name'], 'key': key, 'sha256': sha256, 'size': size, 'verified': verified}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def prune_backups(store, *, backups_root=DEFAULT_ROOT, apply=False):
    root = _root(backups_root)
    with _lock(root):
        local, remote, ignored = {}, {}, []
        for path in sorted(root.iterdir()):
            if path.name.startswith('.'):
                continue
            try:
                source = _snapshot(path, root)
            except (ValueError, OSError):
                ignored.append('local:' + path.name)
                continue
            local[source['key']] = source
        listing = {value.key: value for value in store.list('backups/')}
        for value in listing.values():
            archive = _remote(store, value)
            if archive:
                remote[value.key] = archive
            elif not value.key.endswith('.tar.verified.json'):
                ignored.append('remote:' + value.key)
        snapshots = {**remote, **local}
        ordered = sorted(snapshots, key=lambda key: (snapshots[key]['timestamp'], key), reverse=True)
        keep = set(ordered[:3])
        newest_local = next((key for key in ordered if key in local), None)
        delete_remote = sorted(set(remote) - keep)
        delete_local, blocked = [], []
        for key, source in local.items():
            if key not in keep:
                delete_local.append(source['name'])
            elif key != newest_local:
                if key in remote and _verified(store, remote[key], listing, source['fingerprint']):
                    delete_local.append(source['name'])
                else:
                    blocked.append({'name': source['name'], 'reason': 'matching readback-verified OSS archive required'})
        report = {'applied': apply,
                  'keep': [{'name': snapshots[key]['name'], 'key': key} for key in ordered[:3]],
                  'delete_local': sorted(delete_local), 'delete_remote': delete_remote,
                  'blocked_local': blocked, 'ignored': ignored}
        if apply:
            # Validate all local paths again before the first deletion.
            for source in local.values():
                if source['name'] in delete_local and _snapshot(source['path'], root)['fingerprint'] != source['fingerprint']:
                    raise ValueError('backup changed since retention plan')
            for key in delete_remote:
                # The archive and proof are a pair; unknown neighboring objects are never deleted.
                store.delete(key)
                if key + '.verified.json' in listing:
                    store.delete(key + '.verified.json')
            for source in local.values():
                if source['name'] in delete_local:
                    shutil.rmtree(source['path'])
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--archive', type=Path, metavar='DIRECTORY')
    mode.add_argument('--prune', action='store_true')
    parser.add_argument('--backups-root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--temp-dir', type=Path, default=Path('/var/tmp'))
    parser.add_argument('--verify-readback', action='store_true')
    parser.add_argument('--apply', action='store_true', help='apply the printed retention rules; only valid with --prune')
    args = parser.parse_args(argv)
    if args.apply and not args.prune:
        parser.error('--apply requires --prune')
    if args.verify_readback and not args.archive:
        parser.error('--verify-readback requires --archive')
    try:
        from backend.app.oss_delivery import create_store
        store = create_store()
        if store is None:
            raise ValueError('OSS is not configured')
        report = (archive_snapshot(args.archive, store, backups_root=args.backups_root,
                                   temp_dir=args.temp_dir, verify_readback=args.verify_readback)
                  if args.archive else prune_backups(store, backups_root=args.backups_root, apply=args.apply))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # SDK errors can embed authorization headers or signed request URLs.
        print(json.dumps({'error': 'backup archive operation failed', 'error_type': type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
