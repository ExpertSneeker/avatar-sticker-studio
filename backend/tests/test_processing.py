import io
import numpy as np
import pytest
from PIL import Image, ImageDraw
from backend.app import processing
from backend.app.schemas import PrintSettings
from backend.tests.test_api import png
from backend.tests.helpers import gray_edge_png


def test_print_white_border_is_seven_source_pixels_and_preserves_alpha_and_holes():
    source = gray_edge_png()
    before = Image.open(io.BytesIO(source)).convert('RGBA')
    image = processing.prepare_sticker(source, PrintSettings(long_edge_mm=10, dpi=254))
    assert image.size == (100, 100)
    assert image.getchannel('A').tobytes() == before.crop((10, 10, 110, 110)).getchannel('A').tobytes()
    assert image.getpixel((50, 0)) == (255, 255, 255, 64)
    assert image.getpixel((6, 50)) == (255, 255, 255, 254)
    assert image.getpixel((7, 50)) == (180, 50, 30, 254)
    assert image.getpixel((93, 50)) == (255, 255, 255, 254)
    assert image.getpixel((92, 50)) == (180, 50, 30, 254)
    assert image.getpixel((39, 50)) == (120, 120, 120, 254)
    assert image.getpixel((40, 50))[3] == 0
    assert processing.encode(before) == source


@pytest.mark.parametrize('long_edge_mm,dpi', [(20, 254), (10, 508)])
def test_print_white_border_is_applied_before_physical_resize(long_edge_mm, dpi):
    image = processing.prepare_sticker(gray_edge_png(), PrintSettings(long_edge_mm=long_edge_mm, dpi=dpi))
    assert image.size == (200, 200)
    assert image.getpixel((10, 150))[:3] == (255, 255, 255)
    assert all(abs(actual - expected) <= 1 for actual, expected in zip(image.getpixel((40, 150))[:3], (180, 50, 30)))


def test_print_color_balance_keeps_cleaned_white_border_neutral():
    image = processing.prepare_sticker(gray_edge_png(), PrintSettings(long_edge_mm=10, dpi=254, color_balance=True))
    assert image.getpixel((3, 75)) == (255, 255, 255, 254)
    assert image.getpixel((20, 75))[:3] == (187, 50, 29)


@pytest.mark.parametrize('width,white_x,unchanged_x', [(3, 2, 3), (9, 8, 9)])
def test_print_white_border_uses_configured_source_pixel_width(width, white_x, unchanged_x):
    image = processing.prepare_sticker(gray_edge_png(), PrintSettings(long_edge_mm=10, dpi=254, white_border_px=width))
    assert image.getpixel((white_x, 75))[:3] == (255, 255, 255)
    assert image.getpixel((unchanged_x, 75))[:3] != (255, 255, 255)


def test_zero_white_border_width_disables_cleaning():
    image = processing.prepare_sticker(gray_edge_png(), PrintSettings(long_edge_mm=10, dpi=254, white_border_px=0))
    assert image.getpixel((3, 75))[:3] != (255, 255, 255)


def test_print_white_border_follows_euclidean_contour_even_at_canvas_edges():
    source = Image.new('RGBA', (100, 100), (180, 50, 30, 255))
    source.paste((0, 0, 0, 0), (0, 0, 40, 40))
    image = processing.prepare_sticker(processing.encode(source), PrintSettings(long_edge_mm=10, dpi=254))
    assert image.getpixel((43, 43)) == (255, 255, 255, 255)
    assert image.getpixel((44, 44)) == (180, 50, 30, 255)
    assert image.getpixel((99, 60)) == (255, 255, 255, 255)
    assert image.getpixel((0, 0))[3] == 0



def hazy_edge_image():
    """Red sticker with a 2px gray rim inside 15px of near-invisible dark haze and a sealed-off haze pocket."""
    image = Image.new('RGBA', (120, 120))
    image.paste((40, 40, 40, 5), (15, 15, 105, 105))
    image.paste((150, 150, 150, 170), (30, 30, 90, 90))
    image.paste((180, 50, 30, 254), (32, 32, 88, 88))
    image.paste((0, 0, 0, 0), (20, 50, 28, 60))  # fully transparent, but enclosed by haze
    return image


def test_white_border_starts_at_visible_edge_and_whitens_cutout_haze():
    image, band = processing.whiten_outer_border(hazy_edge_image(), 3)
    assert image.getpixel((30, 40)) == (255, 255, 255, 170)  # gray rim behind 15px of haze
    assert image.getpixel((30, 55)) == (255, 255, 255, 170)  # rim beside the sealed pocket
    assert image.getpixel((32, 40)) == (255, 255, 255, 254)
    assert image.getpixel((33, 40)) == (180, 50, 30, 254)
    assert image.getpixel((20, 40)) == (255, 255, 255, 5)
    assert image.getpixel((22, 55)) == (0, 0, 0, 0)
    assert band.getpixel((20, 40)) == 255 and band.getpixel((33, 40)) == 0


def test_white_border_alpha_one_measures_from_any_nonzero_alpha():
    image, _ = processing.whiten_outer_border(hazy_edge_image(), 3, threshold=1)
    assert image.getpixel((30, 40)) == (150, 150, 150, 170)
    assert image.getpixel((30, 55)) == (150, 150, 150, 170)
    assert image.getpixel((15, 40)) == (255, 255, 255, 5)
    assert image.getpixel((18, 40)) == (40, 40, 40, 5)


def test_prepare_sticker_uses_configured_white_border_alpha():
    data = processing.encode(hazy_edge_image())
    settings = dict(long_edge_mm=18, dpi=127, white_border_px=3)  # 90px content edge keeps source scale
    assert processing.prepare_sticker(data, PrintSettings(**settings)).getpixel((15, 25)) == (255, 255, 255, 170)
    assert processing.prepare_sticker(data, PrintSettings(**settings, white_border_alpha=1)).getpixel((15, 25)) == (150, 150, 150, 170)

def floodfill_exterior(solid):
    outside = Image.fromarray(np.pad(solid.astype(np.uint8) * 255, 1)).copy()
    ImageDraw.floodfill(outside, (0, 0), 128)
    return np.array(outside)[1:-1, 1:-1] == 128


def spiral_walls():
    solid = np.ones((301, 301), bool)
    for k in range(0, 150, 10):
        solid[k + 5:296 - k, k + 5:296 - k] = False
        solid[k + 10:291 - k, k + 10:291 - k] = True
        gap = slice(k + 5, k + 10) if k % 20 == 0 else slice(291 - k, 296 - k)
        solid[150, gap] = False
    return solid


def test_exterior_mask_matches_pil_floodfill():
    rng = np.random.default_rng(1)
    shapes = [rng.random(shape) > p for p in (0.2, 0.5, 0.6, 0.7) for shape in ((1, 1), (1, 50), (50, 1), (97, 131), (300, 300))]
    holes = np.ones((60, 60), bool)
    holes[10:20, 10:20] = holes[20:30, 20:30] = False  # touch only diagonally
    shapes += [spiral_walls(), holes, np.ones((5, 5), bool), np.zeros((5, 5), bool)]
    for solid in shapes:
        assert np.array_equal(processing.exterior_mask(solid), floodfill_exterior(solid))


def test_print_pages_use_faster_png_compression_and_keep_dpi(monkeypatch):
    levels = []
    encode = processing.encode
    monkeypatch.setattr(processing, 'encode', lambda image, dpi=None, compress_level=None: levels.append(compress_level) or encode(image, dpi, compress_level))
    (_, data), = processing.pack_set([png()], 'A', 'B', PrintSettings())
    assert levels == [3]
    assert round(Image.open(io.BytesIO(data)).info['dpi'][0]) == PrintSettings().dpi

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
    assert image.getpixel((500, 500))[3] == 180


def test_overview_is_single_white_full_order_grid():
    assert hasattr(processing, 'overview'), 'full-order overview missing'
    image = Image.open(io.BytesIO(processing.overview([png()] * 24, '员工水印')))
    assert image.size == (1024, 1536)
    assert image.mode == 'RGB'
    assert image.getpixel((0, 0)) == (255, 255, 255)


def test_customer_print_title_appends_seller_remark():
    from backend.app.publication import customer_print_title
    assert customer_print_title({'order_number': '260918-1'}) == '260918-1'
    assert customer_print_title({'order_number': '260918-1', 'platform_remark': ' 已补差价 '}) == '260918-1 已补差价'
    assert customer_print_title({'order_number': '260918-1', 'platform_remark': '长' * 200}) == '260918-1 ' + '长' * 60


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


def content_box(image, title=False):
    import numpy as np
    array=np.array(image.convert('RGBA'))
    mask=(array[:,:,3]>0)&((array[:,:,:3].max(axis=2)==0) if title else (array[:,:,0]>100))
    y,x=np.where(mask)
    assert len(x)>0
    return int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1


def test_print_title_and_sticker_block_are_centered_without_resizing():
    settings=PrintSettings()
    pages=processing.pack_set([png()]*12,'订单甲乙','A01',settings)
    assert len(pages)==2
    for _,data in pages:
        image=Image.open(io.BytesIO(data));w,h=image.size
        x0,y0,x1,y1=content_box(image)
        assert abs(x0-(w-x1))<=1
        assert abs((y0-round(12/25.4*300))-((h-round(10/25.4*300))-y1))<=1
        assert (x1-x0,y1-y0)==(2*1004+118,3*1004+2*118)
        tx0,ty0,tx1,ty1=content_box(image,True)
        assert abs(tx0-(w-tx1))<=2
        assert ty0==round(3/25.4*300) and ty1<y0
        assert image.getpixel((x0+10,y0+10))[3]==180


def test_last_page_and_long_order_titles_fit_and_remain_centered():
    settings=PrintSettings(long_edge_mm=90)
    images=[png(size=(32,20))]*12
    pages=processing.pack_set(images,'订单名字'*20+'甲乙','A01',settings)
    other=processing.pack_set(images,'订单名字'*20+'丙丁','A01',settings)
    assert pages[0][1]!=other[0][1]
    for _,data in pages:
        image=Image.open(io.BytesIO(data));w,h=image.size
        x0,y0,x1,y1=content_box(image)
        assert abs(x0-(w-x1))<=1
        tx0,ty0,tx1,ty1=content_box(image,True)
        assert tx0>=round(10/25.4*300) and tx1<=w-round(10/25.4*300)
        assert ty1<y0 and y1<=h-round(10/25.4*300)
        top=max(round(12/25.4*300),ty1+round(3/25.4*300))
        assert abs((y0-top)-(h-round(10/25.4*300)-y1))<=2


@pytest.mark.parametrize('dpi',[150,600])
def test_print_geometry_at_other_dpi(dpi):
    settings=PrintSettings(dpi=dpi)
    pages=processing.pack_set([png()]*12,'测试订单','SET',settings)
    assert len(pages)==2
    image=Image.open(io.BytesIO(pages[0][1]))
    assert image.info['dpi'][0]==pytest.approx(dpi,abs=.1)
    box=content_box(image)
    assert abs(box[0]-(image.width-box[2]))<=1
    assert content_box(image,True)[3]<box[1]


def test_title_clearance_never_outputs_blank_pages_or_clips_an_oversized_sticker():
    settings=PrintSettings(paper_width_mm=50,paper_height_mm=50,long_edge_mm=50,margin_mm=0)
    with pytest.raises(ValueError,match='标题下方'):
        processing.pack_set([png()]*12,'订单','A',settings)
