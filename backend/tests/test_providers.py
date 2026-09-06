import asyncio
import base64
import json
import httpx
import pytest
from backend.app import providers
from backend.app.providers import ProviderFailure
from backend.tests.test_api import png


def install(monkeypatch, receive):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(receive), **kw))


def test_queue_contract_and_media_isolation(monkeypatch):
    assert hasattr(providers, 'FalProvider')
    seen = []
    states = iter(['IN_QUEUE', 'IN_PROGRESS', 'COMPLETED'])
    base = 'https://queue.fal.run/openai/gpt-image-2/requests/job-1'
    def receive(r):
        seen.append(r)
        if r.method == 'POST':
            assert json.loads(r.content) == dict(prompt='固定提示词', image_urls=['data:image/png;base64,'+base64.b64encode(x).decode() for x in [b'template', b'portrait']], image_size={'width':1024,'height':1024}, quality='low', num_images=1, background='transparent', output_format='png', sync_mode=False)
            return httpx.Response(200, json=dict(request_id='job-1', status_url=base+'/status', response_url=base))
        if r.url.path.endswith('/status'): return httpx.Response(200, json={'status':next(states), 'queue_position':2})
        if r.url.host == 'queue.fal.run': return httpx.Response(200, json={'images':[{'url':'https://v3.fal.media/files/image.png'}]})
        assert 'authorization' not in r.headers
        return httpx.Response(200, content=png())
    install(monkeypatch, receive)
    async def run():
        p = providers.FalProvider('test-key')
        job = await p.submit(b'template', b'portrait', '固定提示词')
        assert job['fal_request_id'] == 'job-1'
        for state in ['IN_QUEUE','IN_PROGRESS','COMPLETED']:
            assert (await p.poll(job))['fal_status'] == state
        assert await p.result(job) == png()
    asyncio.run(run())
    assert str(seen[0].url) == 'https://queue.fal.run/openai/gpt-image-2/edit'
    assert all(r.headers['authorization']=='Key test-key' for r in seen if r.url.host=='queue.fal.run')


@pytest.mark.parametrize('status,expected', [(400,'failed'),(401,'failed'),(429,'retry'),(500,'unknown')])
def test_submit_errors(monkeypatch,status,expected):
    assert hasattr(providers,'FalProvider')
    install(monkeypatch, lambda r:httpx.Response(status,headers={'retry-after':'45'},json={'detail':'secret'}))
    with pytest.raises(ProviderFailure) as e: asyncio.run(providers.FalProvider('secret').submit(b'a',b'b','p'))
    assert e.value.status==expected
    assert 'secret' not in str(e.value)
    if status==429: assert e.value.retry_after==45


@pytest.mark.parametrize('url',['https://evil.test/job','http://queue.fal.run/job','https://queue.fal.run.evil.test/job','https://user:pw@queue.fal.run/job'])
def test_hostile_queue_url_never_receives_key(monkeypatch,url):
    assert hasattr(providers,'FalProvider')
    install(monkeypatch,lambda r:pytest.fail('must validate before network'))
    with pytest.raises(ProviderFailure): asyncio.run(providers.FalProvider('secret').poll({'fal_status_url':url}))


def test_submission_timeout_is_unknown(monkeypatch):
    def fail(r): raise httpx.ReadTimeout('secret',request=r)
    install(monkeypatch,fail)
    with pytest.raises(ProviderFailure) as e: asyncio.run(providers.FalProvider('secret').submit(b'a',b'b','p'))
    assert e.value.status=='unknown' and 'secret' not in str(e.value)


def test_malformed_submission_with_id_retains_canonical_lookup(monkeypatch):
    install(monkeypatch,lambda r:httpx.Response(200,json={'request_id':'job-1','status_url':'https://evil.test','response_url':'https://evil.test'}))
    job=asyncio.run(providers.FalProvider('k').submit(b'a',b'b','p'))
    assert job['fal_request_id']=='job-1'
    assert job['fal_status_url']=='https://queue.fal.run/openai/gpt-image-2/requests/job-1/status'


@pytest.mark.parametrize('body',[{}, {'request_id':123}, {'request_id':'../../evil'}])
def test_missing_or_malformed_id_stays_unknown(monkeypatch,body):
    install(monkeypatch,lambda r:httpx.Response(200,json=body))
    with pytest.raises(ProviderFailure) as e: asyncio.run(providers.FalProvider('k').submit(b'a',b'b','p'))
    assert e.value.status=='unknown'


def test_hostile_media_is_not_downloaded(monkeypatch):
    calls=[]
    def receive(r):
        calls.append(r)
        return httpx.Response(200,json={'images':[{'url':'https://127.0.0.1/secret'}]})
    install(monkeypatch,receive)
    with pytest.raises(ProviderFailure) as e: asyncio.run(providers.FalProvider('k').result({'fal_response_url':'https://queue.fal.run/job'}))
    assert e.value.status=='retry' and len(calls)==1


def test_malformed_url_port_cannot_discard_valid_request_id(monkeypatch):
    install(monkeypatch,lambda r:httpx.Response(200,json={'request_id':'job-1','status_url':'https://queue.fal.run:invalid/path'}))
    job=asyncio.run(providers.FalProvider('k').submit(b'a',b'b','p'))
    assert job['fal_request_id']=='job-1'
