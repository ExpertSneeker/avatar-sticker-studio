"""Alpha-safe image preparation and deterministic physical-size page layout."""
import io
import math
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .schemas import PrintSettings


def encode(image, dpi=None, compress_level=None):
    out = io.BytesIO()
    options = {'dpi': (dpi, dpi)} if dpi else {}
    if compress_level is not None:
        options['compress_level'] = compress_level
    image.save(out, 'PNG', **options)
    return out.getvalue()


def decode(data, require_transparency=True):
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 30_000_000:
            raise ValueError('生成图片尺寸过大')
        image = source.convert('RGBA')
        image.load()
    alpha = image.getchannel('A')
    if not alpha.getbbox():
        raise ValueError('生成图片为空白透明图')
    if require_transparency and alpha.getextrema()[0] == 255:
        raise ValueError('生成图片缺少透明背景，请配置抠图服务后重试')
    return image


def _run_ids(open_):
    """Number each horizontal run of open pixels from 1; closed pixels are 0."""
    starts = open_.copy()
    starts[:, 1:] &= ~open_[:, :-1]
    return np.cumsum(starts, dtype=np.int32).reshape(open_.shape) * open_


def exterior_mask(solid):
    """Transparent pixels 4-connected to the canvas edge, identical to a PIL floodfill."""
    # Padding treats the canvas boundary as exterior even when artwork touches it.
    open_ = np.pad(~solid, 1, constant_values=True)
    rows = _run_ids(open_)
    cols = np.ascontiguousarray(_run_ids(np.ascontiguousarray(open_.T)).T)
    flat = open_.ravel()
    # Each open pixel links one row run with one column run. Spreading reach
    # along those links is vectorized; PIL's floodfill is a per-pixel Python loop.
    r, c = rows.ravel()[flat], cols.ravel()[flat]
    row_hit = np.zeros(rows.max() + 1, bool)
    col_hit = np.zeros(cols.max() + 1, bool)
    row_hit[rows[0]] = True
    row_hit[0] = False
    count = -1
    while True:
        col_hit[c[row_hit[r]]] = True
        row_hit[r[col_hit[c]]] = True
        total = int(row_hit.sum())
        if total == count:
            break
        count = total
    result = np.zeros(open_.size, bool)
    result[flat] = row_hit[r]
    return result.reshape(open_.shape)[1:-1, 1:-1]


def whiten_outer_border(image, width, threshold=128):
    """Whiten a source-pixel band inside the visible outer edge, preserving alpha/holes.

    Pixels below `threshold` alpha that connect to the outside are background, so
    near-invisible cutout haze neither moves the edge outward nor seals off
    pockets as fake interior holes. Those haze pixels are whitened too.
    """
    if not width:
        return image, None
    # Exclude blank padding from the connectivity pass without changing pixel
    # scale. Everything outside the alpha bounds is already exterior background.
    bbox = image.getchannel('A').getbbox()
    array = np.array(image.crop(bbox))
    solid = array[:, :, 3] > 0
    exterior = exterior_mask(array[:, :, 3] >= threshold)
    padded = np.pad(exterior, width, constant_values=True)
    # Row prefix sums dilate with a circular disk in O(width * image pixels),
    # without SciPy or a square filter that would overpaint diagonal corners.
    sums = np.pad(np.cumsum(padded, axis=1, dtype=np.int32), ((0, 0), (1, 0)))
    height, length = solid.shape
    band = np.zeros_like(solid)
    for dy in range(-width, width + 1):
        dx = math.isqrt(width * width - dy * dy)
        row = width + dy
        band |= sums[row:row + height, width + dx + 1:width + dx + 1 + length] != sums[row:row + height, width - dx:width - dx + length]
    band &= solid
    array[band, :3] = 255
    cleaned, white_border = image.copy(), Image.new('L', image.size)
    cleaned.paste(Image.fromarray(array), bbox[:2])
    white_border.paste(Image.fromarray(band.astype(np.uint8) * 255), bbox[:2])
    return cleaned, white_border


def prepare_sticker(data, settings):
    image, white_border = whiten_outer_border(decode(data), settings.white_border_px, settings.white_border_alpha)
    bbox = image.getchannel('A').getbbox()
    image = image.crop(bbox)
    if white_border is not None:
        white_border = white_border.crop(bbox)
    edge = round(settings.long_edge_mm / 25.4 * settings.dpi)
    scale = edge / max(image.size)
    size = tuple(max(1, round(n * scale)) for n in image.size)
    if size != image.size:
        image = image.convert('RGBa').resize(size, Image.Resampling.LANCZOS).convert('RGBA')
        if white_border is not None:
            white_border = white_border.resize(size, Image.Resampling.NEAREST)
    if settings.brightness or settings.color_balance:
        array = np.array(image)
        rgb = array[:, :, :3].astype(np.float32)
        rgb *= np.array([1.04, 1.0, 0.97] if settings.color_balance else [1, 1, 1], dtype=np.float32) * (1.15 if settings.brightness else 1)
        array[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        image = Image.fromarray(array)
    if white_border is not None:
        # Keep the original band white after resampling/color adjustment. Its
        # width was selected above at source resolution, never at print DPI.
        array = np.array(image)
        array[np.array(white_border) > 0, :3] = 255
        image = Image.fromarray(array)
    return image


PRINT_LAYOUT_STYLE = 'order-title-centered-white-border-v3'
# Lossless; level 3 halves full-page encode time on the 2-vCPU server for ~10% larger files.
PRINT_PNG_COMPRESS_LEVEL = 3


def print_header(name, settings, width):
    """Physical title dimensions, measured ink bounds and extra top clearance."""
    px = lambda mm: round(mm / 25.4 * settings.dpi)
    font = watermark_font(name, max(1, px(3)))
    available = width - 2 * max(px(settings.margin_mm), px(3))
    lines, line = [], ''
    for char in name:
        if font.getlength(char) > available:
            raise ValueError('页边距过大，订单标题无法完整显示')
        if line and font.getlength(line + char) > available:
            lines.append(line); line = ''
        line += char
    if line: lines.append(line)
    draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    y, positions = px(3), []
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        positions.append((line, ((width - (box[2] - box[0])) // 2 - box[0], y - box[1])))
        y += box[3] - box[1] + px(1)
    text_bottom = y - px(1)
    top = max(px(settings.margin_mm + 2), text_bottom + px(3))
    return font, positions, top


def pack_set(images, name, code, settings):
    if not images:
        raise ValueError('套装至少需要一张图片')
    px = lambda mm: round(mm / 25.4 * settings.dpi)
    width, height = px(settings.paper_width_mm), px(settings.paper_height_mm)
    margin, gap = px(settings.margin_mm), px(settings.gap_mm)
    font, title, top = print_header(name, settings, width)
    available_width, available_height = width - 2 * margin, height - margin - top
    if available_width <= 0 or available_height <= 0:
        raise ValueError('标题及页边距超出纸张尺寸，请增大纸张或减小页边距')
    pages, placements = [], []
    x = y = row_height = 0

    def finish_page():
        if not placements:
            return
        content_width = max(x + im.width for im, x, y in placements)
        content_height = max(y + im.height for im, x, y in placements)
        offset_x = (width - content_width) // 2
        offset_y = top + (available_height - content_height) // 2
        page = Image.new('RGBA', (width, height))
        for sticker, sx, sy in placements:
            # Preserve semitransparent edges without applying alpha twice.
            page.alpha_composite(sticker, (offset_x + sx, offset_y + sy))
        draw = ImageDraw.Draw(page)
        for text, position in title:
            draw.text(position, text, font=font, fill=(0, 0, 0, 255))
        pages.append((f'{name}_{code}_{len(pages) + 1}.png', encode(page, settings.dpi, PRINT_PNG_COMPRESS_LEVEL)))
        placements.clear()

    for data in images:
        sticker = prepare_sticker(data, settings)
        if sticker.width > available_width or sticker.height > available_height:
            if sticker.height <= available_width and sticker.width <= available_height:
                sticker = sticker.transpose(Image.Transpose.ROTATE_90)
            else:
                raise ValueError('贴纸尺寸超出标题下方的可打印区域，请调整纸张或页边距')
        if x + sticker.width > available_width:
            if sticker.height < sticker.width and x + sticker.height <= available_width and y + sticker.width <= available_height:
                sticker = sticker.transpose(Image.Transpose.ROTATE_90)
            else:
                x, y, row_height = 0, y + row_height + gap, 0
        if y + sticker.height > available_height:
            finish_page()
            x = y = row_height = 0
        placements.append((sticker, x, y))
        x += sticker.width + gap
        row_height = max(row_height, sticker.height)
    finish_page()
    return pages


def overview(images, watermark, group_sizes=None):
    group_sizes = [len(images)] if group_sizes is None else group_sizes
    if not images or not group_sizes or any(type(n) is not int or n < 1 for n in group_sizes) or sum(group_sizes) != len(images):
        raise ValueError('总览必须包含全部完整套装')
    rows = sum((n + 3) // 4 for n in group_sizes)
    canvas = Image.new('RGBA', (1024, 256 * rows), 'white')
    offset, row = 0, 0
    for size in group_sizes:
        for index, data in enumerate(images[offset:offset + size]):
            image = decode(data)
            image = image.convert('RGBa').resize((256, 256), Image.Resampling.LANCZOS).convert('RGBA')
            canvas.alpha_composite(image, ((index % 4) * 256, (row + index // 4) * 256))
        offset += size
        row += (size + 3) // 4
    font = watermark_font(watermark)
    # Wrap every character into measured lines; never clip the last part of a 100-character watermark.
    lines, line = [], ''
    for char in watermark[:100]:
        if line and font.getlength(line + char) > 360:
            lines.append(line)
            line = ''
        line += char
    if line:
        lines.append(line)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 5
    text_tile = Image.new('RGBA', (400, max(95, len(lines) * line_height + 30)))
    shadow = Image.new('RGBA', text_tile.size)
    shadow_draw = ImageDraw.Draw(shadow)
    for index, text in enumerate(lines):
        shadow_draw.text((23, 18 + index * line_height), text, font=font, fill=(0, 0, 0, 105), stroke_width=4, stroke_fill=(0, 0, 0, 105))
    text_tile = Image.alpha_composite(text_tile, shadow.filter(ImageFilter.GaussianBlur(2)))
    draw = ImageDraw.Draw(text_tile)
    for index, text in enumerate(lines):
        position = (20, 14 + index * line_height)
        # Two strokes make even fallback CJK fonts visibly bold with a separate white outline.
        draw.text(position, text, font=font, fill=(55, 55, 55, 110), stroke_width=4, stroke_fill=(255, 255, 255, 205))
        draw.text(position, text, font=font, fill=(55, 55, 55, 110), stroke_width=1, stroke_fill=(55, 55, 55, 110))
    text_tile.putalpha(text_tile.getchannel('A').point(lambda alpha: round(alpha * .65)))
    bbox = text_tile.getbbox()
    if bbox:
        text_tile = text_tile.crop(bbox)
    text_tile = text_tile.rotate(45, resample=Image.Resampling.BICUBIC, expand=True)
    layer = Image.new('RGBA', canvas.size)
    step_x, step_y = max(230, text_tile.width + 10), max(170, text_tile.height + 50)
    for y in range(-100, canvas.height, step_y):
        for x in range(-100, canvas.width, step_x):
            layer.alpha_composite(text_tile, (x, y))
    return encode(Image.alpha_composite(canvas, layer).convert('RGB'))


def watermark_font(text, size=40):
    candidates = [os.environ.get('STUDIO_FONT', ''), '/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Light.ttc', '/System/Library/Fonts/Supplemental/Songti.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for path in candidates:
        if not path or not Path(path).is_file():
            continue
        try:
            font = ImageFont.truetype(path, size)
            missing = font.getmask('\uffff')
            missing_signature = (missing.size, bytes(missing))
            supported = True
            for char in set(text):
                if char.isspace():
                    continue
                glyph = font.getmask(char)
                if (glyph.size, bytes(glyph)) == missing_signature:
                    supported = False
                    break
            if supported:
                return font
        except OSError:
            continue
    raise ValueError('没有支持当前文字的字体，请将STUDIO_FONT设置为支持中文的字体文件路径')
