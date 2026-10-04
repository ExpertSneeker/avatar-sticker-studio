"""Delivery authorization, signed manifests and local ZIP against synthetic orders."""
import io
import zipfile
from urllib.parse import quote
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_customer_orders import opened
from backend.app.customer_orders import delivery_folder
from backend.app.storage import save_asset
from backend.tests.test_organizations import orgs


def seed(app, client):
    order = opened(client, 'SYNTHETIC-OSS', notes='合成备注')
    with app.state.db.transaction() as tx:
        current = tx.get('orders', order['id'])
        asset = save_asset(app.state.db, tx, b'print-only', current['owner'], 'print', order_id=current['id'])
        artifact = {k: asset[k] for k in ('id', 'url', 'sha256', 'size', 'kind')}
        artifact['path'] = '拼版.png'
        artifact['oss_key'] = f"print/{current['organization_id']}/{current['id']}/{asset['sha256']}.png"
        current.update(state='submitted', delivery_ready=True, delivery_version=3, artifacts=[artifact])
        tx.put('orders', current)
    return current, artifact


def test_manifest_adds_local_url_and_no_store_when_disabled(context, monkeypatch):
    app, client, _, _ = context
    monkeypatch.setenv('STUDIO_OSS_BUCKET', '')
    order, artifact = seed(app, client)
    response = client.get(f"/api/customer-orders/{order['id']}/manifest")
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.json()['files'][0]['local_url'] == artifact['url']
    assert response.json()['files'][0]['url'] == artifact['url']
    assert response.json()['version'] == 3


def test_zip_is_stored_and_uses_folder_filename_outside_transaction(context, monkeypatch):
    import backend.app.customer_orders as customer
    app, client, _, _ = context
    order, artifact = seed(app, client)
    real = customer.asset_bytes
    def read(db, asset):
        with db.transaction() as tx:
            tx.put('oss-test', {'id': 'io-outside-tx'})
        return real(db, asset)
    monkeypatch.setattr(customer, 'asset_bytes', read)
    response = client.get(f"/api/customer-orders/{order['id']}/download.zip")
    assert response.status_code == 200
    assert "filename*=UTF-8''" + quote(delivery_folder(order) + '.zip', safe='') in response.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read(delivery_folder(order) + '/' + artifact['path']) == b'print-only'
        assert all(f.compress_type == zipfile.ZIP_STORED for f in archive.infolist())


def test_authorized_manifest_signs_only_expected_key_and_switch_falls_back(context, monkeypatch, caplog):
    from backend.app import oss_delivery
    from backend.tests.test_oss_delivery import MemoryStore
    app, client, _, _ = context
    store = MemoryStore()
    monkeypatch.setattr(oss_delivery, 'create_store', lambda: store)
    order, artifact = seed(app, client)
    path = f"/api/customer-orders/{order['id']}/manifest"
    assert client.get(path).json()['files'][0]['url'].startswith('https://test.invalid/print/')
    monkeypatch.setenv('STUDIO_OSS_DOWNLOAD', '0')
    assert client.get(path).json()['files'][0]['url'] == artifact['url']
    monkeypatch.setenv('STUDIO_OSS_DOWNLOAD', '1')
    store.fail = True
    assert client.get(path).json()['files'][0]['url'] == artifact['url']
    assert 'Signature' not in caplog.text and 'secret.invalid' not in caplog.text
    store.fail = False
    with app.state.db.transaction() as tx:
        order['artifacts'][0]['oss_key'] = 'print/other-org/other-order/' + '0' * 64 + '.png'
        tx.put('orders', order)
    assert client.get(path).json()['files'][0]['url'] == artifact['url']


@pytest.mark.parametrize('denial', ['anonymous', 'guest', 'disabled', 'expired', 'cancelled', 'not-ready'])
def test_unauthorized_manifest_and_zip_never_issue_signed_urls(context, monkeypatch, denial):
    from backend.app import oss_delivery
    app, staff, clock, _ = context
    order, artifact = seed(app, staff)
    def forbidden(key):
        pytest.fail('Signing attempted before successful staff authorization')
    monkeypatch.setattr(oss_delivery, 'sign', forbidden)
    client, expected = staff, 409
    if denial in {'anonymous', 'guest'}:
        client, expected = TestClient(app), 401
        if denial == 'guest':
            assert client.post('/api/guest/login', json={'order_number': order['order_number']}).status_code == 200
    elif denial == 'expired':
        clock.value += 8 * 86400
        expected = 401
    else:
        with app.state.db.transaction() as tx:
            if denial == 'disabled':
                actor = tx.get('users', order['owner'])
                actor['active'] = False
                tx.put('users', actor)
                expected = 401
            else:
                order.update(state='cancelled') if denial == 'cancelled' else order.update(delivery_ready=False)
                tx.put('orders', order)
    for suffix in ('manifest', 'download.zip'):
        assert client.get(f"/api/customer-orders/{order['id']}/{suffix}").status_code == expected


def test_cross_organization_and_disabled_organization_never_sign(orgs, monkeypatch):
    from backend.app import oss_delivery
    app, root, one, two, identities = orgs
    order, artifact = seed(app, one)
    def forbidden(key):
        pytest.fail('Signing attempted for inaccessible organization')
    monkeypatch.setattr(oss_delivery, 'sign', forbidden)
    for suffix in ('manifest', 'download.zip'):
        assert two.get(f"/api/customer-orders/{order['id']}/{suffix}").status_code == 404
    with app.state.db.transaction() as tx:
        org = tx.get('organizations', order['organization_id'])
        org['active'] = False
        tx.put('organizations', org)
    for suffix in ('manifest', 'download.zip'):
        assert one.get(f"/api/customer-orders/{order['id']}/{suffix}").status_code == 401
