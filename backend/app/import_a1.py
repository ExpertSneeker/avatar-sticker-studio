"""Idempotent, source-preserving A1 public-library import (run as service owner)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from PIL import Image
from .db import Database, uid

MARKER = 'a1-public-library-v1'


def read_sources(source):
    result = []
    for n in range(1, 13):
        code = f'A1-{n:02d}'
        path = Path(source) / (code + '.png')
        data = path.read_bytes()
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise ValueError(f'{code}: expected PNG')
            image.verify()
        result.append((code, data, hashlib.sha256(data).hexdigest()))
    return result


def import_a1(db, source):
    sources = read_sources(source)
    fingerprint = hashlib.sha256(json.dumps([(c, h) for c, _, h in sources]).encode()).hexdigest()

    def validate(tx):
        done = tx.get('migrations', MARKER)
        if done:
            if done['source_sha256'] != fingerprint:
                raise ValueError('A1 source changed after completed import; use a reviewed new migration')
            return done
        if any(s['code'].casefold() in {c.casefold() for c, _, _ in sources} for s in tx.all('stickers')):
            raise ValueError('A1 sticker code collision; no active template changed')
        matches = [t for t in tx.all('templates') if not t.get('deleted') and t['code'].casefold() == 'mb-a']
        if len(matches) > 1 or any(t.get('scope', 'public') != 'public' for t in matches):
            raise ValueError('MB-A collision; expected at most one public template')
        return None

    with db.transaction() as tx:
        done = validate(tx)
        if done:
            return {**done, 'already_imported': True}
    # Deterministic asset identities allow resuming after interruption before final switch.
    # Files and public asset records are durable before any active catalog changes.
    images = []
    for code, data, digest in sources:
        asset_id = hashlib.sha256((MARKER + code + digest).encode()).hexdigest()[:32]
        path = db.root / 'assets' / (asset_id + '.png')
        path.parent.mkdir(exist_ok=True, mode=0o700)
        with db.transaction() as tx:
            existing = tx.get('assets', asset_id)
            if existing and (existing.get('sha256') != digest or existing.get('owner') is not None):
                raise ValueError('Staged asset identity collision')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('Staged asset file mismatch')
            else:
                temporary = path.with_suffix('.' + uid() + '.tmp')
                try:
                    with temporary.open('xb') as file:
                        file.write(data)
                        file.flush()
                        os.fsync(file.fileno())
                    os.chmod(temporary, 0o600)
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
            tx.put('assets', {'id':asset_id, 'owner':None, 'scope':'public', 'kind':'template', 'file':path.name, 'sha256':digest, 'size':len(data), 'url':'/api/assets/' + asset_id})
        images.append({'id':asset_id, 'url':'/api/assets/' + asset_id})
    with db.transaction() as tx:
        done = validate(tx)
        if done:
            return {**done, 'already_imported':True}
        sticker_ids = []
        template_images = []
        for position, ((code, _, _), image) in enumerate(zip(sources, images), 1):
            sticker = {'id':uid(), 'code':code, 'name':code, 'category':'general', 'active':True, 'revision':1, 'scope':'public', 'owner':None, 'image':image}
            tx.put('stickers', sticker)
            tx.put('sticker_revisions', {**sticker, 'id':sticker['id'] + ':1', 'sticker_id':sticker['id']})
            sticker_ids.append(sticker['id'])
            template_images.append({**image, 'position':position, 'sticker_id':sticker['id'], 'revision':1, 'active':True, 'code':code})
        archived = []
        for old in tx.all('templates'):
            if not old.get('deleted') and old['code'].casefold() == 'mb-a':
                archived.append(old['id'])
                tx.put('templates', {**old, 'deleted':True, 'active':False})
        # Only retire migration-created members of the removed template. An
        # independently uploaded sticker, or a member reused by any surviving
        # template (including disabled templates), remains in the library.
        migration = tx.get('migrations', 'public-stickers-v1') or {}
        derived = migration.get('derived_sticker_ids_by_template', {})
        candidates = {sid for tid in archived for sid in derived.get(tid, [])}
        retained = {sid for t in tx.all('templates') if not t.get('deleted') for sid in t.get('sticker_ids', [])}
        archived_stickers = []
        for sid in sorted(candidates - retained):
            old_sticker = tx.get('stickers', sid)
            if old_sticker:
                tx.put('stickers', {**old_sticker, 'deleted':True, 'active':False})
                archived_stickers.append(sid)
        template = {'id':uid(), 'name':'模板A', 'code':'MB-A', 'category':'general', 'active':True, 'revision':1, 'scope':'public', 'owner':None, 'sticker_ids':sticker_ids, 'images':template_images}
        tx.put('templates', template)
        tx.put('template_revisions', {**template, 'id':template['id'] + ':1', 'template_id':template['id']})
        done = {'id':MARKER, 'source_sha256':fingerprint, 'template_id':template['id'], 'sticker_ids':sticker_ids, 'archived_template_ids':archived, 'archived_sticker_ids':archived_stickers}
        tx.put('migrations', done)
        return {**done, 'already_imported':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--source-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(import_a1(Database(args.data_dir), args.source_dir), ensure_ascii=False))


if __name__ == '__main__':
    main()
