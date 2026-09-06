"""Real billable providers. Test substitutes are injected at the application boundary."""
import asyncio
import base64
import time
from urllib.parse import urlparse
import httpx
from .db import uid


class ProviderFailure(Exception):
    def __init__(self, message, status='failed', retry_after=30):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


class FalProvider:
    endpoint = 'https://queue.fal.run/openai/gpt-image-2/edit'

    def __init__(self, key):
        self.key = key

    @staticmethod
    def queue_url(url):
        try:
            parsed = urlparse(url if isinstance(url, str) else '')
            port = parsed.port
        except ValueError as exc:
            raise ProviderFailure('FAL队列地址无效，保留请求待确认', 'unknown') from exc
        if parsed.scheme != 'https' or parsed.hostname != 'queue.fal.run' or parsed.username or parsed.password or port not in (None, 443):
            raise ProviderFailure('FAL队列地址无效，保留请求待确认', 'unknown')
        return url

    async def request(self, method, url, payload=None):
        self.queue_url(url)
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                response = await client.request(method, url, headers={'Authorization': 'Key ' + self.key}, **({'json': payload} if payload is not None else {}))
        except httpx.TransportError as exc:
            raise ProviderFailure('FAL连接中断，保留请求等待恢复', 'unknown' if method == 'POST' else 'retry') from exc
        if response.status_code == 429:
            try:
                delay = max(1, float(response.headers.get('retry-after', '30')))
            except ValueError:
                delay = 30
            raise ProviderFailure('FAL限速，等待退避重试', 'retry', delay)
        if response.status_code >= 500:
            raise ProviderFailure('FAL服务暂不可用', 'unknown' if method == 'POST' else 'retry')
        if response.status_code not in (200, 202):
            label = '鉴权失败，请管理员检查FAL密钥' if response.status_code in (401, 403) else '请求被拒绝，请检查输入或内容限制'
            raise ProviderFailure(f'{label}（HTTP {response.status_code}）', 'failed' if method == 'POST' or response.status_code == 422 else 'unknown')
        try:
            body = response.json()
            if not isinstance(body, dict): raise ValueError()
            return body
        except (ValueError, TypeError) as exc:
            raise ProviderFailure('FAL响应不可读取，保留请求待恢复', 'unknown' if method == 'POST' else 'retry') from exc

    async def submit(self, template, avatar, prompt):
        body = await self.request('POST', self.endpoint, dict(prompt=prompt, image_urls=['data:image/png;base64,' + base64.b64encode(x).decode() for x in (template, avatar)], image_size={'width': 1024, 'height': 1024}, quality='low', num_images=1, background='transparent', output_format='png', sync_mode=False))
        request_id = body.get('request_id')
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in request_id):
            raise ProviderFailure('FAL未返回有效请求编号，结果待确认', 'unknown')
        # Derive canonical recovery URLs if a response contains invalid URLs; the ID must survive.
        base = 'https://queue.fal.run/openai/gpt-image-2/requests/' + request_id
        job = dict(fal_request_id=request_id, fal_status='IN_QUEUE', fal_status_url=base + '/status', fal_response_url=base)
        for field, source in [('fal_status_url', 'status_url'), ('fal_response_url', 'response_url')]:
            try:
                job[field] = self.queue_url(body.get(source))
            except ProviderFailure:
                pass
        return job

    async def poll(self, job):
        body = await self.request('GET', job['fal_status_url'])
        status = body.get('status')
        if status not in ('IN_QUEUE', 'IN_PROGRESS', 'COMPLETED'):
            raise ProviderFailure('FAL队列状态不可识别，保留原请求', 'unknown')
        position = body.get('queue_position')
        return {'fal_status': status, 'queue_position': position if isinstance(position, int) and position >= 0 else None}

    async def result(self, job):
        body = await self.request('GET', job['fal_response_url'])
        try:
            url = body['images'][0]['url']
            parsed = urlparse(url)
            host = (parsed.hostname or '').lower()
            if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or not (host.endswith('.fal.media') or host == 'fal.media'):
                raise ValueError()
            async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
                async with client.stream('GET', url) as response:
                    response.raise_for_status()
                    output = bytearray()
                    async for chunk in response.aiter_bytes():
                        output.extend(chunk)
                        if len(output) > 30_000_000: raise ValueError()
                    return bytes(output)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderFailure('FAL图片暂不可读取，将重新获取同一请求结果', 'retry') from exc


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
