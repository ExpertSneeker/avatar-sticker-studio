"""Keep generation records linked to provider requests without financial effects."""


def progress(tx, item):
    # Every FAL request an item ever made, so each one's cost can be matched (retries replace fal_request_id).
    if item.get('fal_request_id') and item['fal_request_id'] not in item.setdefault('fal_request_ids', []):
        item['fal_request_ids'].append(item['fal_request_id'])
    generation = tx.get('generations', item.get('generation_id', ''))
    if generation and item.get('fal_request_id'):
        generation['request_id'] = item['fal_request_id']
        tx.put('generations', generation)
