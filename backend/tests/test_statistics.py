from datetime import datetime, timezone
from backend.tests.test_worker import context
from backend.tests.test_api import order


def test_statistics_permissions_periods_and_current_results(context):
    app, client, clock, _ = context
    first, _ = order(client)
    with app.state.db.transaction() as tx:
        items = tx.all('items')
        items[0].update(status='completed', attempt=3)
        items[1].update(status='failed', attempt=1)
        items[2].update(status='unknown', attempt=1)
        for item in items:
            tx.put('items', item)
    response = client.get('/api/statistics?days=30&offset=480')
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats['summary'] == dict(orders=1, ready_orders=0, images=12, completed=1, failed=1, unknown=1, running=0, queued=9, attempts=5, extra_attempts=2)
    assert stats['order_statuses']['unknown'] == 1
    assert sum(d['orders'] for d in stats['daily']) == 1
    assert stats['templates'][0]['images'] == 12
    assert 'members' not in stats and 'accounts' not in stats
    invite = client.post('/api/admin/invites').json()['code']
    client.post('/api/auth/logout')
    assert client.get('/api/statistics').status_code == 401
    client.post('/api/auth/register', json={'username':'member', 'password':'member-password', 'display_name':'成员', 'invite':invite})
    assert client.get('/api/admin/statistics').status_code == 403
    assert client.get('/api/statistics?scope=global').json()['summary']['orders'] == 0
    from backend.app.credits import record
    member_id=client.get('/api/auth/me').json()['id']
    with app.state.db.transaction() as tx:
        record(tx, member_id, 'adjust', 12, 0, clock(), reason='统计测试初始分配')
    second, _ = order(client, name='成员订单', template_ids=[client.get('/api/templates').json()[0]['id']])
    own = client.get('/api/statistics').json()
    assert own['summary']['orders'] == 1 and own['summary']['completed'] == 0
    client.post('/api/auth/login', json={'username':'admin','password':'safe-password-123'})
    overall = client.get('/api/admin/statistics').json()
    assert overall['summary']['orders'] == 2
    assert len(overall['members']) == 2
    assert overall['accounts'] == {'total':2, 'active':2, 'contributing':2}
    assert client.get('/api/statistics').json()['summary']['orders'] == 1
    assert 'password' not in str(overall) and 'fal_api_key' not in str(overall)
    clock.value += 86400
    assert client.get('/api/statistics?days=1').json()['summary']['orders'] == 1
    clock.value += 1
    assert client.get('/api/statistics?days=1').json()['summary']['orders'] == 0
    assert client.get('/api/statistics?days=0').json()['summary']['orders'] == 1
    assert client.get('/api/statistics?days=2').status_code == 422
    assert client.get('/api/statistics?offset=841').status_code == 422


def test_statistics_local_dates_archive_cleanup_and_no_generation(context):
    app, client, clock, provider = context
    clock.value = datetime(2026,9,5,18,tzinfo=timezone.utc).timestamp()
    client.post('/api/auth/login', json={'username':'admin','password':'safe-password-123'})
    value, _ = order(client)
    with app.state.db.transaction() as tx:
        for item in tx.all('items'):
            item.update(status='completed', attempt=1)
            tx.put('items', item)
        saved = tx.get('orders', value['id'])
        saved.update(overview_ready=True, archived=True, paused=True)
        tx.put('orders', saved)
    stats = client.get('/api/statistics?days=0&offset=480').json()
    assert len(stats['daily']) == 30
    assert stats['order_statuses']['archived'] == 1
    assert stats['summary']['ready_orders'] == 1
    assert next(d for d in stats['daily'] if d['orders'])['date'] == '2026-09-06'
    west = client.get('/api/statistics?offset=-480').json()
    assert next(d for d in west['daily'] if d['orders'])['date'] == '2026-09-05'
    clock.value += 1
    before = datetime.fromtimestamp(clock.value, timezone.utc).isoformat()
    plan = client.post('/api/admin/cleanup/preview',json={'before':before}).json()
    assert client.post('/api/admin/cleanup',json={'before':before,'preview_token':plan['preview_token'],'confirmed':True}).status_code == 200
    stats = client.get('/api/statistics').json()
    assert stats['summary']['orders'] == 0 and stats['templates'] == []
    assert provider.calls == []
