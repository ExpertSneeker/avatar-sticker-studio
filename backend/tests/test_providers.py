import asyncio
import base64
import httpx
import pytest
from backend.app.providers import OpenAIProvider, ProviderFailure
from backend.tests.test_api import png


def test_real_images_edit_multipart_contract(monkeypatch):
    real_client = httpx.AsyncClient
    seen = []
    def receive(request):
        seen.append(request)
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
    transport = httpx.MockTransport(receive)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    result = asyncio.run(OpenAIProvider('test-key').generate(b'template-unique', b'avatar-unique', '固定提示词'))
    assert result == png()
    request = seen[0]
    assert str(request.url) == 'https://api.openai.com/v1/images/edits'
    assert request.method == 'POST'
    assert request.headers['authorization'] == 'Bearer test-key'
    body = request.content
    assert body.index(b'template-unique') < body.index(b'avatar-unique')
    assert b'name="model"\r\n\r\ngpt-image-2' in body
    for field, value in [('quality', 'low'), ('size', '1024x1024'), ('background', 'transparent'), ('output_format', 'png'), ('n', '1')]:
        assert f'name="{field}"\r\n\r\n{value}'.encode() in body
    assert b'input_fidelity' not in body


@pytest.mark.parametrize('status,expected', [(400,'failed'), (401,'failed'), (429,'retry'), (500,'unknown')])
def test_provider_error_classification_and_no_secret_echo(monkeypatch, status, expected):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={'error': {'message': 'should-not-echo-test-key', 'code': 'safety_check_failed'}}, headers={'retry-after': '45'}))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(ProviderFailure) as failure:
        asyncio.run(OpenAIProvider('test-key').generate(b'template', b'avatar', 'prompt'))
    assert failure.value.status == expected
    assert 'test-key' not in str(failure.value)
    if status == 429: assert failure.value.retry_after == 45
