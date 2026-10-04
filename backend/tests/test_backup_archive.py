"""Archive and retention use isolated real tar files and an in-memory OSS boundary."""
import hashlib
import importlib
import importlib.util
import io
import json
import os
import tarfile
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


class MemoryStore:
    def __init__(self):
        self.objects = {}
        self.corrupt_readback = False
        self.uploads = []

    def upload(self, key, body, *, content_type='application/octet-stream', metadata=None, cache_control='private, no-store'):
        data = body if isinstance(body, bytes) else body.read()
        self.objects[key] = (data, dict(metadata or {}))
        self.uploads.append(key)

    def list(self, prefix):
        return [self.head(key) for key in sorted(self.objects) if key.startswith(prefix)]

    def head(self, key):
        body, metadata = self.objects[key]
        return SimpleNamespace(key=key, size=len(body), metadata=metadata, last_modified=datetime.now(timezone.utc))

    @contextmanager
    def read(self, key):
        body = self.objects[key][0]
        if self.corrupt_readback and key.endswith('.tar'):
            body += b'corrupt'
        yield io.BytesIO(body)

    def delete(self, key):
        del self.objects[key]


@pytest.fixture
def archiver():
    assert importlib.util.find_spec('deploy.backup_archive') is not None, 'backup archive implementation is missing'
    return importlib.import_module('deploy.backup_archive')


def snapshot(root, name, second):
    directory = root / name
    (directory / 'data').mkdir(parents=True)
    (directory / 'data' / 'studio.sqlite3').write_bytes(b'sqlite-snapshot-' + name.encode())
    (directory / 'bak.sha').write_text('local verification evidence\n')
    os.utime(directory, (second, second))
    return directory


def archive(archiver, root, path, store, temp, verified=True):
    return archiver.archive_snapshot(path, store, backups_root=root, temp_dir=temp, verify_readback=verified)


def test_archive_is_uncompressed_readback_verified_and_repeat_idempotent(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'
    temp.mkdir()
    path = snapshot(root, 'release-one', 1_700_000_000)
    store = MemoryStore()
    report = archive(archiver, root, path, store, temp)
    key = 'backups/20231114T221320Z-release-one.tar'
    assert report['key'] == key and report['verified']
    data, metadata = store.objects[key]
    assert metadata['sha256'] == hashlib.sha256(data).hexdigest()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tar:
        assert set(tar.getnames()) == {'release-one', 'release-one/bak.sha', 'release-one/data', 'release-one/data/studio.sqlite3'}
        assert tar.extractfile('release-one/data/studio.sqlite3').read() == b'sqlite-snapshot-release-one'
    proof = json.loads(store.objects[key + '.verified.json'][0])
    assert proof['sha256'] == metadata['sha256'] and proof['size'] == len(data)
    assert not list(temp.iterdir())
    result = archive(archiver, root, path, store, temp)
    assert result['key'] == key and result['verified']
    assert store.uploads.count(key) == 1
    assert not list(temp.iterdir())


def test_bad_readback_keeps_source_and_never_writes_verified_evidence(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'
    temp.mkdir()
    path = snapshot(root, 'release-one', 1_700_000_000)
    store = MemoryStore(); store.corrupt_readback = True
    with pytest.raises(ValueError, match='readback'):
        archive(archiver, root, path, store, temp)
    assert path.is_dir()
    assert not any(key.endswith('.verified.json') for key in store.objects)
    assert not list(temp.iterdir())


def test_retention_deduplicates_snapshots_and_uses_creation_time_not_upload_time(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    paths = [snapshot(root, f'release-{i}', 1_700_000_000 + i) for i in range(4)]
    store = MemoryStore()
    # Upload the oldest last: OSS upload timestamps must not change retention order.
    keys = [archive(archiver, root, p, store, temp)['key'] for p in reversed(paths)]
    store.objects['backups/do-not-delete.tar'] = (b'unknown', {})
    before = set(store.objects)
    plan = archiver.prune_backups(store, backups_root=root)
    assert [item['name'] for item in plan['keep']] == ['release-3', 'release-2', 'release-1']
    assert plan['delete_local'] == ['release-0', 'release-1', 'release-2']
    assert plan['delete_remote'] == [keys[-1]]
    assert set(store.objects) == before and all(p.exists() for p in paths)
    applied = archiver.prune_backups(store, backups_root=root, apply=True)
    assert applied['applied'] is True
    assert [p.name for p in root.iterdir() if p.is_dir()] == ['release-3']
    assert len([k for k in store.objects if k.endswith('.tar') and k != 'backups/do-not-delete.tar']) == 3
    assert 'backups/do-not-delete.tar' in store.objects
    assert keys[-1] + '.verified.json' not in store.objects


def test_unverified_retained_local_copies_are_not_deleted(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    first = snapshot(root, 'first', 1_700_000_000)
    latest = snapshot(root, 'latest', 1_700_000_001)
    store = MemoryStore()
    archive(archiver, root, first, store, temp, verified=False)
    plan = archiver.prune_backups(store, backups_root=root, apply=True)
    assert plan['delete_local'] == [] and first.exists() and latest.exists()
    assert any(x['name'] == 'first' for x in plan['blocked_local'])


def test_changed_local_backup_or_remote_metadata_cannot_authorize_local_deletion(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    old = snapshot(root, 'old', 1_700_000_000)
    snapshot(root, 'latest', 1_700_000_002)
    store = MemoryStore()
    key = archive(archiver, root, old, store, temp)['key']
    body, metadata = store.objects[key]
    store.objects[key] = (body, {**metadata, 'sha256': '0' * 64})
    assert archiver.prune_backups(store, backups_root=root, apply=True)['delete_local'] == []
    store.objects[key] = (body, metadata)
    (old / 'data' / 'studio.sqlite3').write_bytes(b'changed')
    assert archiver.prune_backups(store, backups_root=root, apply=True)['delete_local'] == []
    assert old.exists()


@pytest.mark.parametrize('kind', ['outside', 'root-symlink', 'file-symlink', 'directory-symlink'])
def test_archive_rejects_path_escape_and_symlinks(archiver, tmp_path, kind):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    source = snapshot(root, 'safe', 1_700_000_000)
    outside = snapshot(tmp_path / 'outside', 'source', 1_700_000_000)
    if kind == 'outside':
        source = outside
    elif kind == 'root-symlink':
        link = root / 'link'; link.symlink_to(source, target_is_directory=True); source = link
    elif kind == 'file-symlink':
        (source / 'secret').symlink_to(outside / 'data' / 'studio.sqlite3')
    else:
        (source / 'nested').symlink_to(outside, target_is_directory=True)
    store = MemoryStore()
    with pytest.raises(ValueError):
        archive(archiver, root, source, store, temp)
    assert not store.objects and outside.exists() and not list(temp.iterdir())


def test_prune_ignores_unsafe_remote_keys_and_symlinked_local_paths(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    snapshot(root, 'latest', 1_700_000_010)
    outside = snapshot(tmp_path / 'outside', 'source', 1_700_000_000)
    (root / 'old').symlink_to(outside, target_is_directory=True)
    store = MemoryStore()
    keys = ['backups/20230101T000000Z-../source.tar', 'backups/20230101T000000Z-unknown.tar', 'other/20230101T000000Z-old.tar']
    for key in keys: store.objects[key] = (b'unrecognized', {})
    archiver.prune_backups(store, backups_root=root, apply=True)
    assert set(store.objects) == set(keys) and outside.is_dir() and (root / 'old').is_symlink()


def test_archive_refuses_overwriting_existing_unrecognized_object(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    source = snapshot(root, 'release-one', 1_700_000_000)
    store = MemoryStore()
    key = 'backups/20231114T221320Z-release-one.tar'
    store.objects[key] = (b'not-issued-by-this-tool', {})
    with pytest.raises(ValueError, match='refusing to overwrite'):
        archive(archiver, root, source, store, temp)
    assert store.objects[key] == (b'not-issued-by-this-tool', {})
    assert source.exists() and not list(temp.iterdir())


def test_cli_prune_defaults_to_dry_run_and_apply_is_explicit(archiver, tmp_path, monkeypatch, capsys):
    from backend.app import oss_delivery
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    paths = [snapshot(root, f'release-{i}', 1_700_000_000 + i) for i in range(4)]
    store = MemoryStore()
    for source in paths: archive(archiver, root, source, store, temp)
    monkeypatch.setattr(oss_delivery, 'create_store', lambda: store)
    args = ['--prune', '--backups-root', str(root)]
    assert archiver.main(args) == 0
    assert json.loads(capsys.readouterr().out)['applied'] is False
    assert all(source.exists() for source in paths)
    assert archiver.main([*args, '--apply']) == 0
    assert json.loads(capsys.readouterr().out)['applied'] is True
    assert paths[-1].exists() and not any(source.exists() for source in paths[:-1])


def test_cli_errors_never_disclose_provider_authorization(archiver, tmp_path, monkeypatch, capsys):
    from backend.app import oss_delivery
    root = tmp_path / 'backups'; root.mkdir()
    def fail():
        raise RuntimeError('https://secret-bucket/?signature=private-token Authorization: private-key')
    monkeypatch.setattr(oss_delivery, 'create_store', fail)
    assert archiver.main(['--prune', '--backups-root', str(root)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)['error_type'] == 'RuntimeError'
    assert 'private-token' not in output and 'private-key' not in output and 'https://' not in output


def test_later_corrupt_readback_revokes_prior_verification(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'; temp.mkdir()
    source = snapshot(root, 'release-one', 1_700_000_000)
    store = MemoryStore()
    key = archive(archiver, root, source, store, temp)['key']
    assert key + '.verified.json' in store.objects
    store.corrupt_readback = True
    with pytest.raises(ValueError, match='readback'):
        archive(archiver, root, source, store, temp)
    assert key + '.verified.json' not in store.objects and source.exists()


class SDKResponse:
    """Offline HttpResponse boundary; actual SDK StreamBodyReader wraps it."""
    def __init__(self, body):
        self.body = body
        self.chunk_sizes = []
        self.yielded_sizes = []
        self.is_closed = False

    def read(self):
        raise AssertionError('Whole archive/body reads are forbidden')

    def iter_bytes(self, *, block_size):
        self.chunk_sizes.append(block_size)
        for offset in range(0, len(self.body), block_size):
            chunk = self.body[offset:offset + block_size]
            self.yielded_sizes.append(len(chunk))
            yield chunk

    def close(self):
        self.is_closed = True


class SDKMemoryStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.responses = []

    @contextmanager
    def read(self, key):
        from alibabacloud_oss_v2.io_utils import StreamBodyReader
        response = SDKResponse(self.objects[key][0])
        self.responses.append(response)
        stream = StreamBodyReader(response)
        try:
            yield stream
        finally:
            stream.close()


def test_actual_sdk_reader_archive_hash_streams_in_bounded_chunks(archiver):
    from alibabacloud_oss_v2.io_utils import StreamBodyReader
    body = b'x' * (3 * archiver.CHUNK + 17)
    response = SDKResponse(body)
    actual = archiver._hash(StreamBodyReader(response))
    assert actual == (hashlib.sha256(body).hexdigest(), len(body))
    assert len(response.yielded_sizes) == 4 and max(response.yielded_sizes) <= archiver.CHUNK


def test_archive_and_repeat_verification_use_actual_sdk_reader(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'
    temp.mkdir()
    source = snapshot(root, 'sdk-stream', 1_700_000_000)
    store = SDKMemoryStore()
    first = archive(archiver, root, source, store, temp)
    assert first['verified']
    second = archive(archiver, root, source, store, temp)
    assert second['verified'] and second['sha256'] == first['sha256']
    assert all(response.is_closed for response in store.responses)


def test_actual_sdk_verification_marker_rejects_more_than_16k_without_full_read(archiver, tmp_path):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'
    temp.mkdir()
    source = snapshot(root, 'sdk-marker', 1_700_000_000)
    store = MemoryStore()
    key = archive(archiver, root, source, store, temp)['key']
    marker = key + '.verified.json'
    # Valid JSON/proof plus whitespace: only size makes this otherwise-valid proof unsafe.
    proof = store.objects[marker][0]
    response = SDKResponse(proof + b' ' * (100_000 - len(proof)))
    from alibabacloud_oss_v2.io_utils import StreamBodyReader
    @contextmanager
    def read(key):
        yield StreamBodyReader(response)
    store.read = read
    assert not archiver._verified(store, {'key': key, 'info': store.head(key)}, {marker})
    assert sum(response.yielded_sizes) <= 16_385


@pytest.mark.parametrize('sdk_reader', [False, True])
def test_verification_marker_accepts_exact_16k_and_rejects_next_byte(archiver, tmp_path, sdk_reader):
    root, temp = tmp_path / 'backups', tmp_path / 'temp'
    temp.mkdir()
    source = snapshot(root, 'marker-boundary', 1_700_000_000)
    store = SDKMemoryStore() if sdk_reader else MemoryStore()
    key = archive(archiver, root, source, store, temp)['key']
    marker = key + '.verified.json'
    proof = store.objects[marker][0]
    padded = proof + b' ' * (16_384 - len(proof))
    store.objects[marker] = (padded, {})
    remote = {'key': key, 'info': store.head(key)}
    assert archiver._verified(store, remote, {marker})
    store.objects[marker] = (padded + b' ', {})
    assert not archiver._verified(store, remote, {marker})
