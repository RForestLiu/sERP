from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template() -> str:
    return (ROOT / "templates" / "ozon_product_editor.html").read_text(encoding="utf-8")


def test_auto_fill_is_blocked_before_category_is_selected():
    template = read_template()

    assert "function hasSelectedCategory()" in template
    assert "function refreshAutoFillAvailability()" in template
    assert "if (!hasSelectedCategory())" in template
    assert "请先选择 Ozon 分类，再自动填充" in template
    assert '"btn-ai-fill").disabled = !hasSelectedCategory();' in template
