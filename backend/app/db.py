"""SQLite WAL transactions coordinate all processes on one host."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

DEFAULT_PROMPT = '图1是贴纸模板，图2是人物身份参考。将模板中的头部替换为图2中的人物，保留可辨识的五官、发型和脸型。保持模板的身体、服饰、姿势、道具和画风，调整头部角度与衔接，使比例自然。完整保留贴纸主体，不裁断，不增加额外人物、文字、水印或背景，输出透明背景的单张贴纸。'


# Expression indexes for hot lookups. Adding them changes no document; older code ignores them.
INDEXED_FIELDS = ('status', 'remote_reserved', 'state', 'workflow_version', 'order_id', 'order_number', 'guest_order_id', 'customer_order_id')


def uid():
    return uuid4().hex


class Transaction:
    def __init__(self, conn):
        self.conn = conn

    def get(self, kind, id):
        row = self.conn.execute('SELECT doc FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind):
        return [json.loads(row[0]) for row in self.conn.execute('SELECT doc FROM records WHERE kind=? ORDER BY rowid', (kind,))]

    def find(self, kind, *clauses):
        """Rows matching any indexed SQL clause, in all() order. Callers keep their exact Python filters."""
        rows = {}
        for clause, params in clauses:
            for rowid, doc in self.conn.execute(f'SELECT rowid, doc FROM records WHERE kind=? AND ({clause})', (kind, *params)):
                rows[rowid] = doc
        return [json.loads(rows[rowid]) for rowid in sorted(rows)]

    def where(self, kind, field, *values):
        """Rows whose top-level JSON field equals one of values; the field must have an INDEXED_FIELDS index."""
        assert field in INDEXED_FIELDS and values
        return self.find(kind, (f"json_extract(doc,'$.{field}') IN ({','.join('?' * len(values))})", values))

    def count(self, kind):
        return self.conn.execute('SELECT COUNT(*) FROM records WHERE kind=?', (kind,)).fetchone()[0]

    def put(self, kind, doc):
        if kind in {'orders','items','uploads','assets','generations','templates','template_revisions','stickers','sticker_revisions'} and 'organization_id' not in doc:
            parent = self.get('orders', doc.get('order_id','')) or self.get('users', doc.get('owner',''))
            if parent and parent.get('organization_id'):
                doc['organization_id'] = parent['organization_id']
        self.conn.execute('INSERT INTO records(kind,id,doc) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET doc=excluded.doc', (kind, doc['id'], json.dumps(doc, ensure_ascii=False)))
        return doc

    def delete(self, kind, id):
        self.conn.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, id))


class Database:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.path = self.root / 'studio.sqlite3'
        with self.transaction() as tx:
            tx.conn.executescript('CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL,id TEXT NOT NULL,doc TEXT NOT NULL,PRIMARY KEY(kind,id)); CREATE TABLE IF NOT EXISTS starts (family TEXT NOT NULL,at REAL NOT NULL); CREATE INDEX IF NOT EXISTS starts_time ON starts(family,at);')
            for field in INDEXED_FIELDS:
                tx.conn.execute(f"CREATE INDEX IF NOT EXISTS records_{field} ON records(kind, json_extract(doc,'$.{field}'))")
            if not tx.get('config', 'settings'):
                tx.put('config', {'id': 'settings', 'max_inflight': 2, 'prompt': DEFAULT_PROMPT, 'prompt_version': 1})
            config = tx.get('config', 'settings')
            config.pop('rpm', None)
            config.pop('openai_api_key', None)
            tx.put('config', config)
            if not tx.get('migrations', 'personal-credits-v1'):
                for user in tx.all('users'):
                    user.setdefault('credits', {'available':0,'frozen':0,'spent':0,'version':0})
                    tx.put('users', user)
                for kind in ('templates', 'template_revisions'):
                    for template in tx.all(kind):
                        template.setdefault('scope', 'public')
                        template.setdefault('owner', None)
                        tx.put(kind, template)
                for asset in tx.all('assets'):
                    if asset['kind']=='template':
                        asset.setdefault('scope', 'public')
                        tx.put('assets', asset)
                for item in tx.all('items'):
                    item['billing_legacy']=True
                    tx.put('items', item)
                tx.put('migrations', {'id':'personal-credits-v1'})
            if not tx.get('migrations', 'order-shared-rerun-v1'):
                for order in tx.all('orders'):
                    if order.get('workflow_version') != 3:
                        continue
                    limit = int(order.get('generation_limit') or 0)
                    if order.get('rerun_limit') != limit:
                        order['rerun_limit'] = limit
                        order['version'] = order.get('version', 0) + 1
                        tx.put('orders', order)
                tx.put('migrations', {'id':'order-shared-rerun-v1'})
            from .library import migrate_library
            migrate_library(tx)
            from .categories import seed_categories
            seed_categories(tx)
            from .library import migrate_library_status
            migrate_library_status(tx)
            from .organizations import migrate_organizations
            migrate_organizations(tx)
        os.chmod(self.path, 0o600)

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=30000')
            conn.execute('BEGIN IMMEDIATE')
            yield Transaction(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
