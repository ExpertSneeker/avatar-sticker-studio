"""Balance access is site-admin-only; all upstream calls use synthetic HTTP."""
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_customer_orders import opened
from backend.tests.test_organizations import orgs


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch):
    monkeypatch.delenv('FAL_ADMIN_KEY', raising=False)


@pytest.fixture
def upstream(monkeypatch):
    calls = []
    state = {'status': 200, 'data': {'username': 'test-account', 'credits': {'current_balance': 6.92, 'currency': 'USD'}, 'secret': 'must-not-return'}}
    def handle(transport, request):
        calls.append(request)
        if state.get('callback'): state['callback']()
        if state.get('timeout'): raise httpx.ReadTimeout('sensitive upstream detail', request=request)
        return httpx.Response(state['status'], json=state['data'], request=request)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', handle)
    return calls, state


def configure(client):
    response = client.patch('/api/admin/settings', json={'fal_admin_key': 'test-admin-secret'})
    assert response.status_code == 200, response.text
    assert response.json()['fal_balance_configured'] is True
    assert 'test-admin-secret' not in response.text


def test_balance_key_is_separate_private_and_can_be_removed(context, upstream):
    app, client, _, _ = context
    client.patch('/api/admin/settings', json={'fal_api_key': 'test-generation-secret'})
    configure(client)
    assert client.get('/api/admin/settings').json()['fal_balance_configured'] is True
    with app.state.db.transaction() as tx:
        assert tx.get('config', 'settings')['fal_api_key'] == 'test-generation-secret'
    client.patch('/api/admin/settings', json={'max_inflight': 3})
    assert client.get('/api/admin/settings').json()['fal_balance_configured'] is True
    assert client.patch('/api/admin/settings', json={'fal_admin_key': ''}).json()['fal_balance_configured'] is False
    assert client.get('/api/admin/fal/balance').status_code == 409
    assert not upstream[0]


def test_balance_reads_official_endpoint_and_returns_only_safe_fields(context, upstream):
    _, client, clock, _ = context
    configure(client)
    response = client.get('/api/admin/fal/balance')
    assert response.status_code == 200, response.text
    assert response.json() == {'account': 'test-account', 'current_balance': 6.92, 'currency': 'USD', 'queried_at': clock.value}
    assert response.headers['cache-control'] == 'private, no-store'
    assert 'Cookie' in response.headers['vary']
    request = upstream[0][0]
    assert request.method == 'GET'
    assert str(request.url) == 'https://api.fal.ai/v1/account/billing?expand=credits'
    assert request.headers['Authorization'] == 'Key test-admin-secret'
    assert 'secret' not in response.text


def test_balance_environment_key_takes_precedence(context, upstream, monkeypatch):
    _, client, _, _ = context
    configure(client)
    monkeypatch.setenv('FAL_ADMIN_KEY', 'test-env-admin-secret')
    assert client.get('/api/admin/settings').json()['fal_balance_key_source'] == 'environment'
    assert client.get('/api/admin/fal/balance').status_code == 200
    assert upstream[0][0].headers['Authorization'] == 'Key test-env-admin-secret'


def test_balance_rejects_anonymous_guest_other_roles_and_stale_identity(context, upstream):
    app, client, _, _ = context
    configure(client)
    guest = TestClient(app)
    assert guest.get('/api/admin/fal/balance').status_code == 401
    assert guest.post('/api/guest/login', json={'order_number': opened(client)['order_number']}).status_code == 200
    assert guest.get('/api/admin/fal/balance').status_code == 401
    assert guest.patch('/api/admin/settings', json={'fal_admin_key': 'other'}).status_code == 401
    assert client.get('/api/admin/fal/balance', headers={'X-Studio-User': 'other'}).status_code == 401
    with app.state.db.transaction() as tx:
        actor = tx.all('users')[0]
    for role in ('org_admin', 'staff'):
        with app.state.db.transaction() as tx:
            actor['role'] = role
            tx.put('users', actor)
        assert client.get('/api/admin/fal/balance').status_code == 403
        assert client.get('/api/admin/settings').status_code == 403
        assert client.patch('/api/admin/settings', json={'fal_admin_key': 'other'}).status_code == 403
    with app.state.db.transaction() as tx:
        actor.update(role='superadmin', active=False)
        tx.put('users', actor)
    assert client.get('/api/admin/fal/balance').status_code == 401
    assert not upstream[0]


def test_balance_rechecks_account_after_upstream_request(context, upstream):
    app, client, _, _ = context
    configure(client)
    def disable():
        with app.state.db.transaction() as tx:
            actor = tx.all('users')[0]
            actor['active'] = False
            tx.put('users', actor)
    upstream[1]['callback'] = disable
    response = client.get('/api/admin/fal/balance')
    assert response.status_code == 401
    assert '6.92' not in response.text


@pytest.mark.parametrize('status,message', [(401, '密钥无效'), (403, 'ADMIN'), (429, '频繁'), (500, '暂时不可用'), (302, '暂时不可用')])
def test_balance_upstream_errors_do_not_leak_or_log_out_staff(context, upstream, status, message):
    _, client, _, _ = context
    configure(client)
    upstream[1].update(status=status, data={'error': {'message': 'test-admin-secret private detail'}})
    response = client.get('/api/admin/fal/balance')
    assert response.status_code == 502
    assert message in response.json()['detail']
    assert 'test-admin-secret' not in response.text
    assert client.get('/api/auth/me').status_code == 200


@pytest.mark.parametrize('data', [{}, {'credits': {'current_balance': True, 'currency': 'USD'}}, {'credits': {'current_balance': '6.92', 'currency': 'USD'}}, {'credits': {'current_balance': None, 'currency': 'USD'}}])
def test_balance_rejects_malformed_upstream_response(context, upstream, data):
    _, client, _, _ = context
    configure(client)
    upstream[1]['data'] = data
    assert client.get('/api/admin/fal/balance').status_code == 502


def test_balance_timeout_is_safe(context, upstream):
    _, client, _, _ = context
    configure(client)
    upstream[1]['timeout'] = True
    response = client.get('/api/admin/fal/balance')
    assert response.status_code == 504
    assert '超时' in response.text
    assert 'sensitive' not in response.text


def test_balance_is_denied_in_both_organizations(orgs, upstream):
    app, root, one, two, _ = orgs
    configure(root)
    for client in (one, two):
        assert client.get('/api/admin/fal/balance').status_code == 403
        assert client.patch('/api/admin/settings', json={'fal_admin_key': 'other-org-secret'}).status_code == 403
    assert not upstream[0]
    with app.state.db.transaction() as tx:
        actor = tx.all('users')[0]
        actor['organization_id'] = None
        tx.put('users', actor)
    assert root.get('/api/admin/fal/balance').status_code == 200


def test_balance_expires_sessions_and_detects_key_changes(context, upstream):
    app, client, clock, _ = context
    configure(client)
    def change_key():
        with app.state.db.transaction() as tx:
            settings = tx.get('config', 'settings')
            settings['fal_admin_key'] = 'replacement-secret'
            tx.put('config', settings)
    upstream[1]['callback'] = change_key
    response = client.get('/api/admin/fal/balance')
    assert response.status_code == 409
    assert '6.92' not in response.text
    clock.value += 8 * 86400
    assert client.get('/api/admin/fal/balance').status_code == 401
    assert len(upstream[0]) == 1


def test_balance_key_validation_never_echoes_key(context):
    _, client, _, _ = context
    for key in ('test-secret\ninvalid', 'test-secret 无效', 'test-secret\x00'):
        response = client.patch('/api/admin/settings', json={'fal_admin_key': key})
        assert response.status_code == 422
        assert 'test-secret' not in response.text
    response = client.patch('/api/admin/settings', json={'fal_admin_key': ' test-secret '})
    assert response.status_code == 200
    assert 'test-secret' not in response.text
