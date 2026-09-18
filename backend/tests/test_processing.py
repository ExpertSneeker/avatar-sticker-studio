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
