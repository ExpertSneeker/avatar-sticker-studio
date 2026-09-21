"""Authorized, flattened, heavily watermarked derivatives; never original fallback."""
import io
import threading
from collections import OrderedDict
from fastapi import HTTPException, Request, Response
from PIL import Image, ImageDraw
from .processing import watermark_font
from .storage import asset_bytes

PIPELINE = 'guest-light-diagonal-flat-v3'
_cache = OrderedDict()
_lock = threading.Lock()
_CACHE_BYTES = 32 * 1024 * 1024


def render(data, mark, size, already_watermarked=False):
    with Image.open(io.BytesIO(data)) as source:
        source = source.convert('RGBA')
        source.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', source.size, 'white')
        canvas.alpha_composite(source)
    if already_watermarked:
        output = io.BytesIO()
        canvas.convert('RGB').save(output, 'PNG')
        return output.getvalue()
    font_size = max(14, min(32, size // 14))
    font = watermark_font(mark, font_size)
    # Wrap long content into a tile bounded to the image width, repeating all lines.
    lines, current = [], ''
    for char in mark:
        if current and font.getlength(current + char) > max(90, size * .65):
            lines.append(current); current = ''
        current += char
    if current:
        lines.append(current)
    text_height = font_size + 10
    width = max(1, int(max((font.getlength(line) for line in lines), default=1))) + 18
    tile = Image.new('RGBA', (width, text_height * max(1, len(lines)) + 10))
    draw = ImageDraw.Draw(tile)
    for row, line in enumerate(lines):
        draw.text((8, row*text_height), line, font=font, fill=(50, 50, 50, 70), stroke_width=2, stroke_fill=(255, 255, 255, 84))
    tile = tile.rotate(35, resample=Image.Resampling.BICUBIC, expand=True)
    layer = Image.new('RGBA', canvas.size)
    step_x = max(70, tile.width - 10)
    step_y = max(55, tile.height - 5)
    for row, y in enumerate(range(-tile.height//2, canvas.height, step_y)):
        for x in range(-tile.width//2 - (row % 2)*step_x//2, canvas.width, step_x):
            layer.alpha_composite(tile, (x, y))
    output = io.BytesIO()
    Image.alpha_composite(canvas, layer).convert('RGB').save(output, 'PNG')
    return output.getvalue()


def register_guest_media(app, db, user):
    from .customer_orders import customer, digest, guest_order, library_records, scoped

    def authorized(tx, request, order_id, asset_id, version, is_guest):
        if is_guest:
            order = guest_order(tx, request, app.state.clock())
            if order['id'] != order_id:
                raise HTTPException(404, '图片不可用')
        else:
            actor = user(tx, request)
            order = customer(tx, order_id)
            if not scoped(order, actor):
                raise HTTPException(404, '图片不可用')
        if order['state'] == 'cancelled' or order['media_version'] != version:
            raise HTTPException(404, '图片不可用')
        ids = {order.get('overview_id')} if order.get('overview_ready') else set()
        if not is_guest or order['state'] != 'submitted':
            ids.update(a['asset_id'] for a in order['avatars'])
            ids.update(v['asset_id'] for s in order['slots'] for v in s['versions'])
            ids.update(u.get('asset_id') for u in tx.all('uploads') if u.get('guest_order_id') == order_id)
            stickers, _ = library_records(tx, order)
            ids.update(s['image']['id'] for s in stickers)
        asset = tx.get('assets', asset_id)
        if not asset or asset_id not in ids or asset.get('organization_id') != order['organization_id']:
            raise HTTPException(404, '图片不可用')
        return order, asset

    def media(order_id, asset_id, request, v, size, is_guest):
        size = max(160, min(1024, size))
        with db.transaction() as tx:
            order, asset = authorized(tx, request, order_id, asset_id, v, is_guest)
            already_watermarked = (asset['id'] == order.get('overview_id')
                                   and order.get('overview_ready')
                                   and asset.get('kind') == 'overview'
                                   and order.get('overview_style') == 'guest-overview-v1')
            key = digest([asset['id'], asset['sha256'], order['owner'], order['watermark'], order['watermark_version'], v, size, PIPELINE, already_watermarked])
            data = asset_bytes(db, asset)
            mark = order['watermark']
        with _lock:
            rendered = _cache.get(key)
            if rendered is not None:
                _cache.move_to_end(key)
        if rendered is None:
            try:
                rendered = render(data, mark, size, already_watermarked)
            except (OSError, ValueError, Image.DecompressionBombError):
                raise HTTPException(422, '图片预览暂不可用')
            with _lock:
                _cache[key] = rendered
                while sum(len(x) for x in _cache.values()) > _CACHE_BYTES:
                    _cache.popitem(last=False)
        # Cancellation/watermark replacement during rendering must invalidate this response.
        with db.transaction() as tx:
            authorized(tx, request, order_id, asset_id, v, is_guest)
            return Response(rendered, media_type='image/png', headers={'Cache-Control': 'no-store', 'Content-Disposition': 'inline'})

    @app.get('/api/guest/media/{order_id}/{asset_id}')
    def guest_image(order_id: str, asset_id: str, request: Request, v: int, size: int = 640):
        return media(order_id, asset_id, request, v, size, True)

    @app.get('/api/customer-orders/{order_id}/media/{asset_id}')
    def staff_image(order_id: str, asset_id: str, request: Request, v: int, size: int = 640):
        return media(order_id, asset_id, request, v, size, False)
