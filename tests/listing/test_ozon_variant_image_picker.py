from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template() -> str:
    return (ROOT / "templates" / "ozon_product_editor.html").read_text(encoding="utf-8")


def test_variant_image_area_can_pick_images_from_product_image_sets():
    template = read_template()

    assert "variantImages: {}" in template
    assert 'data-action="pick-variant-images"' in template
    assert 'id="variant-image-modal"' in template
    assert "function openVariantImagePicker(variantKey)" in template
    assert 'api("/api/products/" + encodeURIComponent(pageState.skc) + "/images")' in template
    assert "renderVariantImageSetPicker" in template
    assert "confirmVariantImages" in template
    assert "pageState.variantImages[pageState.activeVariantKey]" in template
    assert "renderVariantSelectedImages" in template
    assert "function collectSkuRows()" in template
    assert "images: pageState.variantImages[variantKey] || []" in template
    assert "skus: collectSkuRows()" in template


def test_variant_info_uses_separate_length_width_height_inputs():
    template = read_template()

    assert "<th>长(cm)</th><th>宽(cm)</th><th>高(cm)</th>" in template
    assert "<th>尺寸(cm)</th>" not in template
    assert "depth: inputs[4] ? inputs[4].value.trim() : \"\"" in template
    assert "width: inputs[5] ? inputs[5].value.trim() : \"\"" in template
    assert "height: inputs[6] ? inputs[6].value.trim() : \"\"" in template
    assert "weight: inputs[7] ? inputs[7].value.trim() : \"\"" in template
