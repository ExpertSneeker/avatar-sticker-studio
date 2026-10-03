"""Authorized, flattened, heavily watermarked derivatives; never original fallback."""
import io
import threading
from collections import OrderedDict
from fastapi import HTTPException, Request, Response
from PIL import Image, ImageDraw
from .processing import watermark_font
from .storage import asset_bytes

PIPELINE = 'guest-light-diagonal-flat-webp-v4'
# Fixed derivative tiers: any requested size snaps up to one, so arbitrary sizes cannot multiply renders or fragment the cache.
TIERS = (160, 320, 640, 1024)
# Thumbnail tiers are downscaled from a 640 render, so their watermark looks exactly like the 640 preview shrunk by the browser.
WATERMARK_REFERENCE = 640
THUMBNAIL_QUALITY = 80
_lock = threading.Lock()
# In-process only (lost on restart). 256MB holds every thumbnail tier of the whole library for several watermarks.
_CACHE_BYTES = 256 * 1024 * 1024


class _ByteLRU(OrderedDict):
    """LRU bounded by total value bytes; the running total avoids re-summing every entry per insert."""

    def __init__(self, limit):
        super().__init__()
        self.limit, self.bytes = limit, 0

    def put(self, key, value):
        if key in self:
            self.bytes -= len(self.pop(key))
        self[key] = value
        self.bytes += len(value)
        while self.bytes > self.limit:
            self.bytes -= len(self.popitem(last=False)[1])

    def clear(self):
        super().clear()
        self.bytes = 0


_cache = _ByteLRU(_CACHE_BYTES)


def tier(size):
    return next((value for value in TIERS if value >= size), TIERS[-1])


def pipeline(size):
    # 640/1024 keep the previous pipeline so existing browser validators stay valid.
    return PIPELINE if size >= WATERMARK_REFERENCE else f'{PIPELINE}-ref{WATERMARK_REFERENCE}-q{THUMBNAIL_QUALITY}'


def encode_preview(image, quality=90):
    # Lossy WebP (q90) is ~5x smaller than PNG for these flattened previews; originals and print files stay PNG.
    output = io.BytesIO()
    image.convert('RGB').save(output, 'WEBP', quality=quality, method=4)
    return output.getvalue()


def render(data, mark, size, already_watermarked=False):
    if already_watermarked or size >= WATERMARK_REFERENCE:
        return encode_preview(watermarked(data, mark, size, already_watermarked))
    image = watermarked(data, mark, WATERMARK_REFERENCE)
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    return encode_preview(image, THUMBNAIL_QUALITY)


def watermarked(data, mark, size, already_watermarked=False):
    with Image.open(io.BytesIO(data)) as source:
        source = source.convert('RGBA')
        source.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', source.size, 'white')
        canvas.alpha_composite(source)
    if already_watermarked:
        return canvas
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
    return Image.alpha_composite(canvas, layer)


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
            ids.update(u.get('asset_id') for u in tx.where('uploads', 'guest_order_id', order_id) if u.get('guest_order_id') == order_id)
            stickers, _ = library_records(tx, order)
            ids.update(s['image']['id'] for s in stickers)
        asset = tx.get('assets', asset_id)
        if not asset or asset_id not in ids or asset.get('organization_id') != order['organization_id']:
            raise HTTPException(404, '图片不可用')
        return order, asset

    def media(order_id, asset_id, request, v, size, is_guest):
        size = tier(size)
        candidates = [tag.strip().removeprefix('W/') for tag in request.headers.get('if-none-match', '').split(',')]

        def prepare(tx):
            order, asset = authorized(tx, request, order_id, asset_id, v, is_guest)
            already_watermarked = (asset['id'] == order.get('overview_id')
                                   and order.get('overview_ready')
                                   and asset.get('kind') == 'overview'
                                   and order.get('overview_style') == 'guest-overview-v1')
            key = digest([asset['id'], asset['sha256'], order['owner'], order['watermark'], order['watermark_version'], v, size, pipeline(size), already_watermarked])
            mark = order['watermark']
            with _lock:
                rendered = _cache.get(key)
                if rendered is not None:
                    _cache.move_to_end(key)
            # A browser cache hit needs live authorization, but no image IO/encoding.
            not_modified = '*' in candidates or f'"{key}"' in candidates
            return key, mark, already_watermarked, rendered, asset_bytes(db, asset) if rendered is None and not not_modified else None

        key, mark, already_watermarked, rendered, data = db.read(prepare)
        headers = {'Cache-Control': 'private, no-cache', 'Vary': 'Cookie', 'ETag': f'W/"{key}"'}
        if '*' in candidates or f'"{key}"' in candidates:
            db.read(lambda tx: authorized(tx, request, order_id, asset_id, v, is_guest))
            return Response(status_code=304, headers=headers)
        if rendered is None:
            try:
                rendered = render(data, mark, size, already_watermarked)
            except (OSError, ValueError, Image.DecompressionBombError):
                raise HTTPException(422, '图片预览暂不可用')
            with _lock:
                _cache.put(key, rendered)
        # Cancellation/watermark replacement during rendering must invalidate this response.
        db.read(lambda tx: authorized(tx, request, order_id, asset_id, v, is_guest))
        return Response(rendered, media_type='image/webp', headers={**headers, 'Content-Disposition': 'inline'})

    @app.get('/api/guest/media/{order_id}/{asset_id}')
    def guest_image(order_id: str, asset_id: str, request: Request, v: int, size: int = 640):
        return media(order_id, asset_id, request, v, size, True)

    @app.get('/api/customer-orders/{order_id}/media/{asset_id}')
    def staff_image(order_id: str, asset_id: str, request: Request, v: int, size: int = 640):
        return media(order_id, asset_id, request, v, size, False)
