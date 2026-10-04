"""Keep generation records linked to provider requests without financial effects."""


def progress(tx, item):
    generation = tx.get('generations', item.get('generation_id', ''))
    if generation and item.get('fal_request_id'):
        generation['request_id'] = item['fal_request_id']
        tx.put('generations', generation)
