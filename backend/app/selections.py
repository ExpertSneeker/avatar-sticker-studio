"""Freeze public library choices into unique work and repeatable output occurrences."""
from collections import Counter
from copy import deepcopy
from fastapi import HTTPException
from .db import uid
from .library import hydrate_template


def expand_selection(tx, template_ids, sticker_ids):
    if len(set(template_ids)) != len(template_ids) or len(set(sticker_ids)) != len(sticker_ids):
        raise HTTPException(422, '不能重复选择同一模板或贴纸')
    snapshots, occurrences = [], []

    def selected_sticker(id):
        sticker = tx.get('stickers', id)
        if not sticker or not sticker.get('active') or sticker.get('deleted'):
            raise HTTPException(422, '所选贴纸或模板成员不存在或已下架，请重新选择')
        return deepcopy(sticker)

    for id in template_ids:
        template = tx.get('templates', id)
        if not template or not template.get('active') or template.get('deleted'):
            raise HTTPException(422, '所选模板不存在或已移除，请重新选择')
        members = [selected_sticker(sid) for sid in template.get('sticker_ids', [])]
        if not 1 <= len(members) <= 100:
            raise HTTPException(422, '模板成员无效，请重新选择')
        snapshots.append({**deepcopy(hydrate_template(tx, template)), 'stickers': members})
        occurrences.extend((s, 'template', id, pos) for pos, s in enumerate(members, 1))
    occurrences.extend((selected_sticker(id), 'sticker', id, pos) for pos, id in enumerate(sticker_ids, 1))
    if not 1 <= len(occurrences) <= 360:
        raise HTTPException(422, '每个订单需选择1至360份导出贴纸，请拆分订单')
    unique, entries, copies = {}, [], Counter()
    for s, source_type, source_id, position in occurrences:
        key = (s['id'], s['revision'])
        if key not in unique:
            unique[key] = {'id':uid(), 'sticker':s}
        copies[key] += 1
        entries.append({'item_id':unique[key]['id'], 'sticker_id':s['id'], 'code':s['code'], 'revision':s['revision'],
                        'source_type':source_type, 'source_id':source_id, 'position':position, 'copy_index':copies[key]})
    return snapshots, list(unique.values()), entries
