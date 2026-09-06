"""Current-state statistics, grouped by order submission time (not billing events)."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone


def summarize(tx, actor, now, days=30, offset=480, global_scope=False):
    zone = timezone(timedelta(minutes=offset))
    current = datetime.fromtimestamp(now, zone)
    cutoff = now - days * 86400 if days else None
    orders = []
    for order in tx.all('orders'):
        if not global_scope and order['owner'] != actor['id']:
            continue
        submitted = datetime.fromisoformat(order['created_at']).timestamp()
        if submitted > now or cutoff is not None and submitted < cutoff:
            continue
        orders.append(order)
    selected = {o['id'] for o in orders}
    by_order = defaultdict(list)
    for item in tx.all('items'):
        if item['order_id'] in selected:
            by_order[item['order_id']].append(item)
    total = Counter(orders=len(orders))
    statuses = Counter()
    templates, members = {}, {}
    # Bound chart payload even when the user requests all retained orders.
    first_day = (current - timedelta(days=days if days else 29)).date()
    daily = {str(first_day + timedelta(days=i)): {'date':str(first_day + timedelta(days=i)), 'orders':0, 'images':0}
             for i in range((current.date() - first_day).days + 1)}
    for order in orders:
        items = by_order[order['id']]
        counts = Counter(i['status'] for i in items)
        total['images'] += len(items)
        for status in ('completed', 'failed', 'unknown', 'running', 'queued'):
            total[status] += counts[status]
        total['attempts'] += sum(i.get('attempt', 0) for i in items)
        total['extra_attempts'] += sum(max(0, i.get('attempt', 0) - 1) for i in items)
        done = bool(items) and counts['completed'] == len(items) and order.get('overview_ready')
        status = ('archived' if order.get('archived') else 'paused' if order.get('paused') else
                  'unknown' if counts['unknown'] else 'failed' if counts['failed'] or order.get('processing_error') else
                  'completed' if done else 'processing' if counts['running'] or counts['completed'] else 'queued')
        statuses[status] += 1
        total['ready_orders'] += int(bool(done))
        member = members.setdefault(order['owner'], {'id':order['owner'], 'orders':0, 'images':0, 'completed':0, 'failed':0, 'attempts':0})
        member['orders'] += 1
        member['images'] += len(items)
        member['completed'] += counts['completed']
        member['failed'] += counts['failed']
        member['attempts'] += sum(i.get('attempt', 0) for i in items)
        day = str(datetime.fromisoformat(order['created_at']).astimezone(zone).date())
        if day in daily:
            daily[day]['orders'] += 1
            daily[day]['images'] += len(items)
        for code in order['template_codes']:
            entry = templates.setdefault(code, {'code':code, 'orders':0, 'images':0, 'completed':0, 'failed':0})
            group = [i for i in items if i['set_code'] == code]
            entry['orders'] += 1
            entry['images'] += len(group)
            entry['completed'] += sum(i['status'] == 'completed' for i in group)
            entry['failed'] += sum(i['status'] == 'failed' for i in group)
    keys = ('orders', 'ready_orders', 'images', 'completed', 'failed', 'unknown', 'running', 'queued', 'attempts', 'extra_attempts')
    result = {'scope':'global' if global_scope else 'personal', 'days':days,
              'generated_at':current.isoformat(), 'summary':{k:total[k] for k in keys},
              'order_statuses':{k:statuses[k] for k in ('queued','processing','completed','failed','unknown','paused','archived')},
              'daily':list(daily.values()),
              'templates':sorted(templates.values(), key=lambda v:(-v['orders'], v['code']))}
    if global_scope:
        users = tx.all('users')
        identities = {u['id']:u for u in users}
        for member in members.values():
            account = identities.get(member['id'], {})
            member.update(display_name=account.get('display_name', '已移除账号'), username=account.get('username', ''), active=account.get('active', False))
        result['members'] = sorted(members.values(), key=lambda v:(-v['orders'], v['id']))
        result['accounts'] = {'total':len(users), 'active':sum(bool(u['active']) for u in users), 'contributing':len(members)}
    return result
