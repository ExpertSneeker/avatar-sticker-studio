"""The staff handbook is private content, not a public frontend asset."""
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_customer_orders import opened


def test_staff_guide_requires_staff_session_even_for_authenticated_guest(context):
    app, staff, _, _ = context
    number = opened(staff)['order_number']
    guest = TestClient(app)
    assert guest.get('/api/staff-guide').status_code == 401
    assert guest.post('/api/guest/login', json={'order_number': number}).status_code == 200
    denied = guest.get('/api/staff-guide')
    assert denied.status_code == 401
    assert '开户与额度' not in denied.text


def test_staff_guide_is_available_to_regular_accounts_and_not_cached(context):
    app, admin, _, _ = context
    invite = admin.post('/api/admin/invites').json()['code']
    member = TestClient(app)
    registered = member.post('/api/auth/register', json={'invite': invite, 'username': 'guide-reader', 'password': 'safe-password-123', 'display_name': '说明读者'})
    assert registered.status_code == 200
    response = member.get('/api/staff-guide')
    assert response.status_code == 200
    guide = response.json()
    assert guide['title'] == '后台使用说明'
    assert {'orders', 'guest', 'printing', 'shops', 'changes'} <= {s['id'] for s in guide['sections']}
    assert response.headers['cache-control'] == 'private, no-store'
    assert 'Cookie' in response.headers['vary']
    assert member.get('/api/staff-guide', headers={'X-Studio-User': 'another-account'}).status_code == 401
    member.post('/api/auth/logout')
    assert member.get('/api/staff-guide').status_code == 401


def test_staff_guide_revalidates_disabled_and_expired_accounts(context):
    app, staff, clock, _ = context
    assert staff.get('/api/staff-guide').status_code == 200
    with app.state.db.transaction() as tx:
        actor = tx.all('users')[0]
        actor['active'] = False
        tx.put('users', actor)
    assert staff.get('/api/staff-guide').status_code == 401
    with app.state.db.transaction() as tx:
        actor['active'] = True
        tx.put('users', actor)
    clock.value += 8 * 86400
    assert staff.get('/api/staff-guide').status_code == 401
