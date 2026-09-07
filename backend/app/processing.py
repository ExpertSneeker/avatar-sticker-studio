"""Alpha-safe image preparation and deterministic physical-size page layout."""
import io
import math
import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .schemas import PrintSettings


def encode(image, dpi=None):
    out = io.BytesIO()
    image.save(out, 'PNG', **({'dpi': (dpi, dpi)} if dpi else {}))
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


def prepare_sticker(data, settings):
    image = decode(data)
    image = image.crop(image.getchannel('A').getbbox())
    edge = round(settings.long_edge_mm / 25.4 * settings.dpi)
    scale = edge / max(image.size)
    size = tuple(max(1, round(n * scale)) for n in image.size)
    image = image.convert('RGBa').resize(size, Image.Resampling.LANCZOS).convert('RGBA')
    if settings.brightness or settings.color_balance:
        array = np.array(image)
        rgb = array[:, :, :3].astype(np.float32)
        rgb *= np.array([1.04, 1.0, 0.97] if settings.color_balance else [1, 1, 1], dtype=np.float32) * (1.15 if settings.brightness else 1)
        array[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        image = Image.fromarray(array)
    return image


PRINT_LAYOUT_STYLE = 'order-title-centered-v1'


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
    if len(images) != 12:
        raise ValueError('仅发布完整的12张套装')
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
        pages.append((f'{name}_{code}_{len(pages) + 1}.png', encode(page, settings.dpi)))
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


def overview(images, watermark):
    if not images or len(images) % 12:
        raise ValueError('总览必须包含全部完整套装')
    canvas = Image.new('RGBA', (1024, 768 * (len(images) // 12)), 'white')
    for index, data in enumerate(images):
        image = decode(data)
        image = image.convert('RGBa').resize((256, 256), Image.Resampling.LANCZOS).convert('RGBA')
        canvas.alpha_composite(image, ((index % 4) * 256, (index // 4) * 256))
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
