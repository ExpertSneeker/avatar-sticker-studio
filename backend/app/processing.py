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


def pack_set(images, name, code, settings):
    if len(images) != 12:
        raise ValueError('仅发布完整的12张套装')
    px = lambda mm: round(mm / 25.4 * settings.dpi)
    width, height = px(settings.paper_width_mm), px(settings.paper_height_mm)
    margin, gap = px(settings.margin_mm), px(settings.gap_mm)
    page = Image.new('RGBA', (width, height))
    pages, x, y, row_height = [], margin, margin, 0
    for data in images:
        sticker = prepare_sticker(data, settings)
        if x + sticker.width > width - margin:
            if sticker.height < sticker.width and x + sticker.height <= width - margin and y + sticker.width <= height - margin:
                sticker = sticker.transpose(Image.Transpose.ROTATE_90)
            else:
                x, y, row_height = margin, y + row_height + gap, 0
        if y + sticker.height > height - margin:
            pages.append((f'{name}_{code}_{len(pages) + 1}.png', encode(page, settings.dpi)))
            page = Image.new('RGBA', (width, height))
            x, y, row_height = margin, margin, 0
        if sticker.width > width - 2 * margin or sticker.height > height - 2 * margin:
            raise ValueError('贴纸尺寸超出可打印区域')
        # alpha_composite preserves source alpha; paste(image, mask=image) squares it.
        page.alpha_composite(sticker, (x, y))
        x += sticker.width + gap
        row_height = max(row_height, sticker.height)
    pages.append((f'{name}_{code}_{len(pages) + 1}.png', encode(page, settings.dpi)))
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
    bbox = text_tile.getbbox()
    if bbox:
        text_tile = text_tile.crop(bbox)
    text_tile = text_tile.rotate(45, resample=Image.Resampling.BICUBIC, expand=True)
    layer = Image.new('RGBA', canvas.size)
    step_x, step_y = max(260, text_tile.width + 35), max(150, text_tile.height + 25)
    for y in range(-100, canvas.height, step_y):
        for x in range(-100, canvas.width, step_x):
            layer.alpha_composite(text_tile, (x, y))
    return encode(Image.alpha_composite(canvas, layer).convert('RGB'))


def watermark_font(text):
    candidates = [os.environ.get('STUDIO_FONT', ''), '/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Light.ttc', '/System/Library/Fonts/Supplemental/Songti.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for path in candidates:
        if not path or not Path(path).is_file():
            continue
        try:
            font = ImageFont.truetype(path, 40)
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
    raise ValueError('没有支持当前水印文字的字体，请将STUDIO_FONT设置为支持中文的字体文件路径')
