"""Customer-made images: uploaded finished artwork printed without generation, taking print and preview budget."""
import hashlib
import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.tests.test_worker import context
from backend.tests.test_api import png, upload
from backend.tests.test_mixed_stickers import sticker
from backend.tests.test_customer_orders import action, opened, run


def rgb(size=(600, 400), color=(40, 120, 200)):
    out = io.BytesIO(); Image.new('RGB', size, color).save(out, 'PNG'); return out.getvalue()


def send(client, data, purpose='design', name='作品.png', prefix='/api/uploads'):
    init = client.post(prefix+'/init', json={'filename': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'purpose': purpose})
    assert init.status_code == 200, init.text
    assert client.put(prefix+'/'+init.json()['id'], content=data, headers={'Upload-Offset': '0'}).status_code == 200
    done = client.post(prefix+'/'+init.json()['id']+'/complete'); assert done.status_code == 200, done.text
    return done.json()


def stored(app, upload_id):
    with app.state.db.transaction() as tx:
        u = tx.get('uploads', upload_id)
        return Image.open(io.BytesIO((app.state.db.root/'assets'/tx.get('assets', u['asset_id'])['file']).read_bytes()))


@pytest.fixture
def cutouts(context, monkeypatch):
    from backend.app import worker as worker_module
    app = context[0]
    with app.state.db.transaction() as tx:
        config = tx.get('config', 'settings'); config['cutout_api_key'] = 'local-test-only'; tx.put('config', config)
    class Cutout:
        calls = 0
        def __init__(self, *args): pass
        async def cutout(self, data):
            Cutout.calls += 1
            return png(size=Image.open(io.BytesIO(data)).size)
    monkeypatch.setattr(worker_module, 'YeziProvider', Cutout)
    return Cutout


def test_designs_only_order_prints_without_generation(context, cutouts):
    app, c, _, provider = context
    whole, cut = send(c, rgb()), send(c, rgb((300, 300), (200, 30, 30)), name='抠图.png')
    o = opened(c, generation_limit=3, final_count=2)
    designs = [{'upload_id': whole['id'], 'cutout': 'whole'}, {'upload_id': cut['id']}]
    saved = c.put('/api/customer-orders/'+o['id']+'/draft', json={'avatars': [], 'designs': designs})
    assert saved.status_code == 200, saved.text
    draft = saved.json()['draft']['designs']
    assert [d['cutout'] for d in draft] == ['whole', 'cutout'] and all(d['preview_url'] for d in draft)
    assert saved.json()['design_count'] == 2
    pre = action(c, saved.json(), 'preflight', designs=designs).json()
    assert pre == {'avatar_count': 0, 'selection_count': 2, 'generation_count': 0, 'design_count': 2}
    o = action(c, saved.json(), 'generate', designs=designs).json()
    assert o['state'] == 'review' and [s['source'] for s in o['slots']] == ['design', 'design']
    assert [s['sticker_code'] for s in o['slots']] == ['自备图', '自备图'] and all(s['group_size'] == 1 for s in o['slots'])
    run(app); run(app)
    assert provider.calls == [] and cutouts.calls == 1
    o = c.get('/api/customer-orders/'+o['id']).json()
    assert all(s['status'] == 'completed' and s['selected_version_id'] for s in o['slots'])
    assert action(c, o, 'slots/'+o['slots'][0]['id']+'/rerun').status_code == 409
    o = action(c, o, 'submit', slot_ids=[s['id'] for s in o['slots']]).json()
    app.state.worker.publish(o['id'])
    o = c.get('/api/customer-orders/'+o['id']).json()
    assert o['delivery_ready'] and o['preview_url'], o.get('processing_error')
    assert all(s['reruns_used'] == 0 for s in o['slots'])
    # Statistics count generation work only.
    assert c.get('/api/statistics').json()['summary']['images'] == 0


def test_whole_prints_keep_the_rectangle_and_overview_keeps_the_shape():
    from backend.app.processing import overview, prepare_sticker
    from backend.app.schemas import PrintSettings
    printed = prepare_sticker(rgb((600, 400)), PrintSettings(white_border_px=0))
    assert printed.getchannel('A').getextrema() == (255, 255)
    assert abs(printed.width / printed.height - 1.5) < 0.01
    sheet = Image.open(io.BytesIO(overview([rgb((600, 300))], '水印'))).convert('RGB')
    # A wide image is centred in its square cell, leaving the cell's top white.
    assert sheet.getpixel((128, 10)) == (255, 255, 255) and sheet.getpixel((128, 128)) != (255, 255, 255)


def test_designs_share_the_preview_budget_and_keep_purposes_apart(context):
    app, c, _, _ = context
    sid = sticker(c, 'ONE')['id']
    avatar, design = upload(c), send(c, rgb())
    o = opened(c, generation_limit=2, final_count=1)
    body = {'avatars': [{'upload_id': avatar['id'], 'template_ids': [], 'sticker_ids': [sid, sid]}], 'designs': [{'upload_id': design['id']}]}
    assert action(c, o, 'preflight', **body).status_code == 422
    assert c.put('/api/customer-orders/'+o['id']+'/draft', json=body).status_code == 422
    # An avatar is not a design and a design is not an avatar.
    assert action(c, o, 'preflight', designs=[{'upload_id': avatar['id']}]).status_code == 422
    assert action(c, o, 'preflight', avatars=[{'upload_id': design['id'], 'template_ids': [], 'sticker_ids': [sid]}]).status_code == 422
    # More designs than the print count is never useful.
    second = send(c, rgb(color=(1, 2, 3)), name='二.png')
    assert action(c, o, 'preflight', designs=[{'upload_id': design['id']}, {'upload_id': second['id']}]).status_code == 422
    body['avatars'][0]['sticker_ids'] = [sid]
    assert action(c, o, 'preflight', **body).json() == {'avatar_count': 1, 'selection_count': 2, 'generation_count': 1, 'design_count': 1}


def test_large_designs_shrink_to_a_2048_long_edge_and_keep_transparency(context):
    app, c, _, _ = context
    big = send(c, png(size=(3000, 1000)))
    assert stored(app, big['id']).size == (2048, 683) and stored(app, big['id']).mode == 'RGBA'
    small = send(c, rgb((800, 500)))
    assert stored(app, small['id']).size == (800, 500)
    # The same file uploaded as an avatar is a separate record with avatar sizing.
    assert upload(c, png(size=(3000, 1000)))['id'] != big['id']


def test_replace_swaps_or_switches_mode_for_free_and_keeps_history(context, cutouts):
    app, c, _, provider = context
    sid = sticker(c, 'ONE')['id']
    first = send(c, rgb())
    o = opened(c, generation_limit=3, final_count=2, rerun_limit=0)
    o = action(c, o, 'generate', avatars=[{'upload_id': upload(c)['id'], 'template_ids': [], 'sticker_ids': [sid]}], designs=[{'upload_id': first['id']}]).json()
    design = next(s for s in o['slots'] if s['source'] == 'design')
    assert design['cutout'] == 'cutout'
    assert action(c, o, 'slots/'+design['id']+'/replace', upload_id=first['id'], cutout='whole').status_code == 409  # still processing
    run(app); run(app)
    o = c.get('/api/customer-orders/'+o['id']).json()
    sticker_slot = next(s for s in o['slots'] if s['source'] == 'sticker')
    assert action(c, o, 'slots/'+sticker_slot['id']+'/replace', upload_id=first['id']).status_code == 409
    o = action(c, o, 'slots/'+design['id']+'/replace', upload_id=first['id'], cutout='whole').json()
    design = next(s for s in o['slots'] if s['source'] == 'design')
    assert design['cutout'] == 'whole' and design['status'] == 'queued'
    run(app)
    o = c.get('/api/customer-orders/'+o['id']).json()
    design = next(s for s in o['slots'] if s['source'] == 'design')
    assert len(design['versions']) == 2 and design['selected_version_id'] == design['versions'][1]['id'] and not design['pending_version_id']
    assert cutouts.calls == 1 and len(provider.calls) == 1 and sum(s['reruns_used'] for s in o['slots']) == 0
    # Any earlier version can still be kept.
    o = action(c, o, 'slots/'+design['id']+'/select', version_id=design['versions'][0]['id']).json()
    assert next(s for s in o['slots'] if s['source'] == 'design')['selected_version_id'] == design['versions'][0]['id']


def test_guest_designs_upload_in_review_and_stay_private(context, cutouts):
    app, c, _, _ = context
    o = opened(c, generation_limit=2, final_count=1)
    guest = TestClient(app); assert guest.post('/api/guest/login', json={'order_number': o['order_number']}).status_code == 200
    first = send(guest, rgb(), prefix='/api/guest/uploads')
    assert first['preview_url'] and 'asset_id' not in first
    g = guest.put('/api/guest/order/draft', json={'avatars': [], 'designs': [{'upload_id': first['id'], 'cutout': 'whole'}]})
    assert g.status_code == 200, g.text
    link = g.json()['draft']['designs'][0]['preview_url']
    assert guest.get(link).status_code == 200
    g = guest.post('/api/guest/order/generate', json={'client_token': 'gen', 'expected_version': g.json()['version'], 'designs': [{'upload_id': first['id'], 'cutout': 'whole'}]})
    assert g.status_code == 200, g.text
    run(app)
    # Avatars are fixed once generation starts; customer-made images may still be swapped.
    data = png()
    avatar = guest.post('/api/guest/uploads/init', json={'filename': 'a.png', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    assert avatar.status_code == 409
    second = send(guest, rgb(color=(9, 9, 9)), name='新.png', prefix='/api/guest/uploads')
    g = guest.get('/api/guest/order').json()
    slot = g['slots'][0]
    assert slot['source'] == 'design' and slot['cutout'] == 'whole' and 'raw_available' not in slot
    g = guest.post('/api/guest/order/slots/'+slot['id']+'/replace', json={'client_token': 'swap', 'expected_version': g['version'], 'upload_id': second['id'], 'cutout': 'cutout'})
    assert g.status_code == 200, g.text
    run(app)
    g = guest.get('/api/guest/order').json()
    assert g['slots'][0]['status'] == 'completed' and len(g['slots'][0]['versions']) == 2 and cutouts.calls == 1
    # Another order's guest cannot use these uploads.
    other = opened(c, 'OTHER', generation_limit=2, final_count=1)
    stranger = TestClient(app); stranger.post('/api/guest/login', json={'order_number': other['order_number']})
    assert stranger.put('/api/guest/order/draft', json={'designs': [{'upload_id': second['id']}]}).status_code == 422
