"""Real billable providers. Test substitutes are injected at the application boundary."""
import asyncio
import base64
import ipaddress
import os
import time
from urllib.parse import urlparse
import httpx
from .db import uid


class ProviderFailure(Exception):
    def __init__(self, message, status='failed', retry_after=30):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class OpenAIProvider:
    def __init__(self, key):
        self.key = key

    async def generate(self, template, avatar, prompt):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=20), follow_redirects=False) as client:
                response = await client.post('https://api.openai.com/v1/images/edits', headers={'Authorization': 'Bearer ' + self.key}, data={'model': 'gpt-image-2', 'quality': 'low', 'size': '1024x1024', 'background': 'transparent', 'output_format': 'png', 'n': '1', 'prompt': prompt}, files=[('image[]', ('template.png', template, 'image/png')), ('image[]', ('avatar.png', avatar, 'image/png'))])
        except httpx.TransportError as exc:
            raise ProviderFailure('API连接中断或超时，结果待确认；不会自动再次扣费请求', 'unknown') from exc
        if response.status_code == 429:
            try:
                delay = min(600, max(1, float(response.headers.get('retry-after', '30'))))
            except ValueError:
                delay = 30
            raise ProviderFailure('OpenAI限速，等待退避重试', 'retry', delay)
        if response.status_code >= 500:
            raise ProviderFailure('OpenAI服务异常，结果待确认；请人工确认后决定重跑', 'unknown')
        if response.status_code != 200:
            code = ''
            try:
                code = str(response.json().get('error', {}).get('code', ''))
            except ValueError:
                pass
            label = '内容被拒绝' if 'moderation' in code or 'safety' in code else '鉴权失败，请管理员检查API密钥' if response.status_code in (401, 403) else '请求被拒绝，请检查模板、头像及提示词'
            raise ProviderFailure(f'{label}（HTTP {response.status_code}）')
        try:
            payload = response.json()['data'][0]['b64_json']
            if len(payload) > 60_000_000:
                raise ValueError('payload too large')
            return base64.b64decode(payload, validate=True)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderFailure('API已响应但图片结果不可读取，请人工确认', 'unknown') from exc


class YeziProvider:
    def __init__(self, db, key, clock=time.time):
        self.db, self.key, self.clock = db, key, clock

    async def cutout(self, data):
        # A separate transactional limiter: at most 2 starts/second and 2 in flight.
        call_id = uid()
        while True:
            with self.db.transaction() as tx:
                now = self.clock()
                for c in tx.all('cutout_calls'):
                    if c['expires'] < now:
                        tx.delete('cutout_calls', c['id'])
                count = tx.conn.execute('SELECT COUNT(*) FROM starts WHERE family=? AND at>?', ('cutout', now - 1)).fetchone()[0]
                admitted = count < 2 and len(tx.all('cutout_calls')) < 2
                if admitted:
                    tx.conn.execute('INSERT INTO starts(family,at) VALUES(?,?)', ('cutout', now))
                    tx.put('cutout_calls', {'id': call_id, 'expires': now + 360})
            if admitted:
                break
            await asyncio.sleep(0.25)
        try:
            async with httpx.AsyncClient(timeout=330, follow_redirects=False) as client:
                response = await client.post('https://coco-openapi.yezisheji.com/api/v1/segment/submit', headers={'X-API-KEY': self.key}, data={'sync': '1', 'output_format': 'png', 'timeout': '300'}, files={'image_file': ('sticker.png', data, 'image/png')})
                if response.status_code != 200:
                    raise ProviderFailure(f'抠图失败（HTTP {response.status_code}），原始生成结果已保留')
                body = response.json()
                url = body.get('data', {}).get('image') if body.get('status') == 200 else None
                if not url:
                    raise ProviderFailure('抠图服务未返回图片，原始生成结果已保留')
                parsed = urlparse(url)
                # Provider output is a public OSS image, never an arbitrary internal URL.
                host = (parsed.hostname or '').lower()
                if parsed.scheme != 'https' or not (host.endswith('.aliyuncs.com') or host.endswith('.yezisheji.com')):
                    raise ProviderFailure('抠图下载地址不在受信任的HTTPS域名中')
                async with client.stream('GET', url) as download:
                    download.raise_for_status()
                    output = bytearray()
                    async for chunk in download.aiter_bytes():
                        output.extend(chunk)
                        if len(output) > 30_000_000:
                            raise ProviderFailure('抠图结果尺寸超限')
                return bytes(output)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderFailure('抠图服务连接或响应异常，原始生成结果已保留') from exc
        finally:
            with self.db.transaction() as tx:
                tx.delete('cutout_calls', call_id)
