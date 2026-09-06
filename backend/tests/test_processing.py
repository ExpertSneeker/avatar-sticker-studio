import io
import pytest
from PIL import Image
from backend.app import processing
from backend.app.schemas import PrintSettings
from backend.tests.test_api import png


def test_trim_resize_keeps_semtransparent_alpha_and_physical_size():
    assert hasattr(processing, 'prepare_sticker'), 'alpha-safe sticker preparation missing'
    image = processing.prepare_sticker(png(), PrintSettings())
    assert image.size == (1004, 1004)
    assert image.getextrema()[3] == (180, 180)


def test_packing_page_dimensions_names_and_dpi():
    assert hasattr(processing, 'pack_set'), 'transparent page packing missing'
    pages = processing.pack_set([png()] * 12, '小明', 'A01', PrintSettings())
    assert [name for name, data in pages] == ['小明_A01_1.png', '小明_A01_2.png']
    image = Image.open(io.BytesIO(pages[0][1]))
    assert image.size == (2480, 3508)
    assert image.info['dpi'][0] == pytest.approx(300, abs=0.1)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((130, 130))[3] == 180


def test_overview_is_single_white_full_order_grid():
    assert hasattr(processing, 'overview'), 'full-order overview missing'
    image = Image.open(io.BytesIO(processing.overview([png()] * 24, '员工水印')))
    assert image.size == (1024, 1536)
    assert image.mode == 'RGB'
    assert image.getpixel((0, 0)) == (255, 255, 255)


def test_cjk_watermarks_render_distinct_glyphs_and_keep_long_text_tail():
    first = processing.overview([png()] * 12, '甲乙丙丁')
    second = processing.overview([png()] * 12, '春夏秋冬')
    assert first != second
    prefix = '头像贴纸仅供内部预览' * 6
    assert processing.overview([png()] * 12, prefix + '甲乙') != processing.overview([png()] * 12, prefix + '春夏')


def test_missing_usable_watermark_font_fails_with_actionable_error(monkeypatch):
    monkeypatch.setattr(processing.Path, 'is_file', lambda self: False)
    with pytest.raises(ValueError, match='STUDIO_FONT'):
        processing.overview([png()] * 12, '中文水印')
