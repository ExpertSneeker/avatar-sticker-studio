"""FAL input selection uses local isolated databases, with no provider or OSS I/O."""
import pytest
from fastapi.testclient import TestClient

from backend.app.db import Database
from backend.tests.helpers import member
from backend.tests.test_api import app, client
from backend.tests.test_organizations import orgs


def test_missing_setting_defaults_inline_and_migration_preserves_other_settings(tmp_path):
    db = Database(tmp_path)
    with db.transaction() as tx:
        settings = tx.get('config', 'settings')
        assert settings['fal_input_mode'] == 'inline'
        settings.pop('fal_input_mode')
        settings.update(max_inflight=7, max_uploads=4, prompt_version=9)
        tx.put('config', settings)
    restarted = Database(tmp_path)
    with restarted.transaction(readonly=True) as tx:
        migrated = tx.get('config', 'settings')
        assert migrated == {**settings, 'fal_input_mode': 'inline'}
    with restarted.transaction() as tx:
        tx.put('config', {**migrated, 'fal_input_mode': 'oss'})
    Database(tmp_path)
    with restarted.transaction(readonly=True) as tx:
        assert tx.get('config', 'settings')['fal_input_mode'] == 'oss'


def test_unconfigured_oss_forces_effective_inline_and_rejects_oss_atomically(client, app, monkeypatch):
    monkeypatch.setenv('STUDIO_OSS_BUCKET', '  ')
    with app.state.db.transaction() as tx:
        stored = tx.get('config', 'settings')
        stored.update(fal_input_mode='oss')
        tx.put('config', stored)
    result = client.get('/api/admin/settings')
    assert result.status_code == 200
    assert result.json()['fal_input_mode'] == 'inline'
    assert result.json()['fal_input_oss_available'] is False
    response = client.patch('/api/admin/settings', json={'fal_input_mode': 'oss', 'max_inflight': 6})
    assert response.status_code == 422
    assert 'OSS' in response.json()['detail']
    with app.state.db.transaction(readonly=True) as tx:
        assert tx.get('config', 'settings') == stored
    assert client.patch('/api/admin/settings', json={'fal_input_mode': 'inline'}).json()['fal_input_mode'] == 'inline'


def test_configured_oss_mode_can_be_switched_without_changing_queue_controls(client, app, monkeypatch):
    monkeypatch.setenv('STUDIO_OSS_BUCKET', 'synthetic-test-bucket')
    before = client.get('/api/admin/settings').json()
    assert before['fal_input_mode'] == 'inline' and before['fal_input_oss_available'] is True
    for mode in ('oss', 'inline', 'oss'):
        response = client.patch('/api/admin/settings', json={'fal_input_mode': mode})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['fal_input_mode'] == mode and result['fal_input_oss_available'] is True
        for key in ('max_inflight', 'max_uploads', 'fal_upload_timeout', 'prompt', 'prompt_version'):
            assert result[key] == before[key]
        with app.state.db.transaction(readonly=True) as tx:
            assert tx.get('config', 'settings')['fal_input_mode'] == mode
    monkeypatch.delenv('STUDIO_OSS_BUCKET')
    assert client.get('/api/admin/settings').json()['fal_input_mode'] == 'inline'
    monkeypatch.setenv('STUDIO_OSS_BUCKET', 'synthetic-test-bucket')
    assert client.get('/api/admin/settings').json()['fal_input_mode'] == 'oss'


@pytest.mark.parametrize('value', ['unknown', '', 'OSS', True, 1, None, ['oss']])
def test_invalid_input_modes_cannot_change_settings(client, app, monkeypatch, value):
    monkeypatch.setenv('STUDIO_OSS_BUCKET', 'synthetic-test-bucket')
    with app.state.db.transaction(readonly=True) as tx:
        before = tx.get('config', 'settings')
    assert client.patch('/api/admin/settings', json={'fal_input_mode': value}).status_code == 422
    with app.state.db.transaction(readonly=True) as tx:
        assert tx.get('config', 'settings') == before


def test_availability_is_derived_read_only(client, monkeypatch):
    monkeypatch.delenv('STUDIO_OSS_BUCKET', raising=False)
    response = client.patch('/api/admin/settings', json={'fal_input_oss_available': True})
    assert response.status_code == 422
    assert client.get('/api/admin/settings').json()['fal_input_oss_available'] is False


def test_only_active_superadmin_can_read_or_change_input_mode(orgs, monkeypatch):
    app, root, org_admin, _, _ = orgs
    monkeypatch.setenv('STUDIO_OSS_BUCKET', 'synthetic-test-bucket')
    staff, _ = member(org_admin, app, 'mode-staff')
    order = org_admin.post('/api/customer-orders', json={'platform':'pdd','order_number':'MODE-TEST','generation_limit':1,'final_count':1,'rerun_limit':0,'client_token':'mode'}).json()
    guest = TestClient(app)
    assert guest.post('/api/guest/login', json={'order_number':order['order_number']}).status_code == 200
    anonymous = TestClient(app)
    for actor, status in ((org_admin,403),(staff,403),(guest,401),(anonymous,401)):
        assert actor.get('/api/admin/settings').status_code == status
        assert actor.patch('/api/admin/settings', json={'fal_input_mode':'oss'}).status_code == status
    assert root.patch('/api/admin/settings', json={'fal_input_mode':'oss'}).status_code == 200
    user = root.get('/api/auth/me').json()
    with app.state.db.transaction() as tx:
        value = tx.get('users', user['id']); value['active'] = False; tx.put('users', value)
    assert root.get('/api/admin/settings').status_code == 401
    assert root.patch('/api/admin/settings', json={'fal_input_mode':'inline'}).status_code == 401
