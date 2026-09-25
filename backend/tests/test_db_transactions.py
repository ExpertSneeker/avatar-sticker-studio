"""Read snapshots never write, fall back to a write transaction when needed, and do not wait for writers."""
import os
import time
import pytest
from backend.app.db import Database, NeedsWrite


def test_readonly_transaction_refuses_writes_before_touching_the_database(tmp_path):
    db = Database(tmp_path)
    with pytest.raises(NeedsWrite):
        with db.transaction(readonly=True) as tx:
            tx.put('config', {**tx.get('config', 'settings'), 'marker': 1})
    with db.transaction() as tx:
        assert 'marker' not in tx.get('config', 'settings')


def test_read_reruns_writing_callbacks_in_a_write_transaction(tmp_path):
    db = Database(tmp_path)
    calls = []

    def bump(tx):
        calls.append(tx.readonly)
        config = tx.get('config', 'settings')
        config['counter'] = config.get('counter', 0) + 1
        tx.put('config', config)
        return config['counter']

    assert db.read(bump) == 1 and calls == [True, False]
    assert db.read(lambda tx: tx.get('config', 'settings')['counter']) == 1


def test_read_snapshot_does_not_wait_for_an_open_writer(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as writer:
        writer.put('config', {**writer.get('config', 'settings'), 'pending': True})
        started = time.monotonic()
        value = db.read(lambda tx: tx.get('config', 'settings'))
        assert time.monotonic() - started < 1
        assert 'pending' not in value  # Uncommitted writes stay invisible.
    assert db.read(lambda tx: tx.get('config', 'settings'))['pending'] is True


def test_idle_anchor_keeps_the_wal_between_transactions(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        tx.put('config', {**tx.get('config', 'settings'), 'touched': True})
    assert os.path.exists(str(db.path) + '-wal')
    db.close()
    db.close()  # Idempotent.
    reopened = Database(tmp_path)
    assert reopened.read(lambda tx: tx.get('config', 'settings'))['touched'] is True
