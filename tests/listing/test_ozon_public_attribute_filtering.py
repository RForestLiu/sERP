from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ozon_editor_filters_public_attributes_out_of_gray_product_area():
    template = read_text("templates/ozon_product_editor.html")

    assert "PUBLIC_OZON_ATTRIBUTE_IDS" in template
    for attr_id in ("85", "8229", "4180", "4191", "9024", "23171", "11254", "22232", "21837", "8789", "8790"):
        assert attr_id in template
    assert "function isPublicOzonAttribute(attr)" in template
    assert "var dynamicAttrs = attrs.filter(function (attr) { return !isPublicOzonAttribute(attr); });" in template
    assert "pageState.categoryAttributes = dynamicAttrs;" in template
    assert "当前分类没有返回非公共产品属性" in template


def test_listing_docs_define_cross_platform_public_attribute_area_rule():
    requirements = read_text("docs/需求文档.md")
    handoff = read_text("docs/交接文档.md")

    assert "灰色产品属性区域只展示非公共属性" in requirements
    assert "后续 Amazon、Wildberries 等平台也沿用同一规则" in requirements
    assert "公共属性由固定区域承接" in handoff
    assert "动态属性区只渲染当前分类的非公共属性" in handoff


def test_ozon_dynamic_attribute_fill_inputs_have_no_placeholder():
    template = read_text("templates/ozon_product_editor.html")

    assert 'data-attr-type="\' + esc(attr.type || "String") + \'" placeholder=' not in template
    assert 'data-attr-manual="\' + id + \'" placeholder=' not in template
