"""Isolated browser-test server. Never used by the production launcher."""
import atexit
import io
import os
import tempfile

from PIL import Image, ImageDraw
from backend.app.main import create_app


class BrowserTestProvider:
    async def generate(self, template, avatar, prompt):
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


def factory():
    root = tempfile.TemporaryDirectory(prefix='avatar-studio-browser-test-')
    atexit.register(root.cleanup)
    os.environ['STUDIO_ALLOWED_ORIGINS'] = 'http://127.0.0.1:5174'
    app = create_app(root.name, provider=BrowserTestProvider())
    with app.state.db.transaction() as tx:
        settings = tx.get('config', 'settings')
        settings.update(max_inflight=8)
        tx.put('config', settings)
    return app
