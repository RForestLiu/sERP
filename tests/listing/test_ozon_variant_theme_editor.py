from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template() -> str:
    return (ROOT / "templates" / "ozon_product_editor.html").read_text(encoding="utf-8")


def test_variant_theme_can_be_added_edited_removed_and_drives_rows():
    template = read_template()

    assert "variantThemes:" in template
    assert 'id="variant-theme-list"' in template
    assert 'data-action="add-variant-theme"' in template
    assert "function renderVariantThemes()" in template
    assert "function addVariantTheme()" in template
    assert "function updateVariantTheme(index, field, value)" in template
    assert "function removeVariantTheme(index)" in template
    assert "function renderVariantInfoRows()" in template
    assert "function renderVariantImageRows()" in template
    assert "pageState.variantThemes.forEach" in template
    assert "delete pageState.variantImages[theme.key];" in template
