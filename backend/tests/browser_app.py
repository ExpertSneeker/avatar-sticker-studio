"""Isolated browser-test server. Never used by the production launcher."""
import atexit
import io
import os
import tempfile
from collections import Counter

from PIL import Image, ImageDraw
from backend.app import worker as worker_module
from backend.app.main import create_app
from backend.app.providers import ProviderFailure


class BrowserTestProvider:
    def __init__(self):
        self.attempts = Counter()

    async def generate(self, template, avatar, prompt):
        # A solid magenta template (e2e/fixtures/fail-once.png) alternates: each fresh generation fails
        # once as an unsent upload, then its retry succeeds.
        with Image.open(io.BytesIO(template)) as source:
            if source.convert('RGBA').getpixel((0, 0)) == (255, 0, 255, 255):
                self.attempts[template] += 1
                if self.attempts[template] % 2:
                    raise ProviderFailure('连接或上传到FAL失败，请求未送达，可重试', 'failed')
        # Deliberately synthetic test pixels, with real alpha and 1K dimensions.
        image = Image.new('RGBA', (1024, 1024))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((230, 210, 790, 950), radius=170, fill='#ed9874')
        draw.ellipse((190, 80, 830, 720), fill='#ffddb9')
        draw.ellipse((350, 310, 390, 370), fill='#47352d')
        draw.ellipse((635, 310, 675, 370), fill='#47352d')
        draw.arc((405, 385, 625, 515), 0, 180, fill='#a65d4d', width=18)
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()


class BrowserTestCutout:
    """Stands in for Yezi. A cyan background (e2e/fixtures/cutout-refused-*.png) is refused once per image,
    as Yezi answers a bad request, then cut out; other images are cut out at once."""
    attempts = Counter()

    def __init__(self, *args):
        pass

    async def cutout(self, data):
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert('RGBA')
        if image.getpixel((0, 0))[:3] == (0, 255, 255):
            BrowserTestCutout.attempts[data] += 1
            if BrowserTestCutout.attempts[data] % 2:
                failure = ProviderFailure('抠图失败（HTTP 400：测试拒绝），原始生成结果已保留')
                failure.cutout_ended = True
                raise failure
        background = image.getpixel((0, 0))
        image.putdata([(0, 0, 0, 0) if pixel == background else pixel for pixel in image.getdata()])
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()


def factory():
    root = tempfile.TemporaryDirectory(prefix='avatar-studio-browser-test-')
    atexit.register(root.cleanup)
    os.environ['STUDIO_ALLOWED_ORIGINS'] = 'http://127.0.0.1:5174'
    worker_module.YeziProvider = BrowserTestCutout
    app = create_app(root.name, provider=BrowserTestProvider())
    with app.state.db.transaction() as tx:
        settings = tx.get('config', 'settings')
        settings.update(max_inflight=8, cutout_api_key='browser-test-only')
        tx.put('config', settings)
    return app
