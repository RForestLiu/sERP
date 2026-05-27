from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template() -> str:
    return (ROOT / "templates" / "ozon_product_editor.html").read_text(encoding="utf-8")


def test_json_rich_content_area_is_editable_and_included_in_payload():
    template = read_template()

    assert 'textarea class="rich-json-editor" id="rich-json-input"' in template
    assert "function collectRichContentValue()" in template
    assert "function collectWorkbenchAttributes()" in template
    assert "attribute_id: 11254" in template
    assert "rich_content: collectRichContentValue()" in template
    assert "attributes: collectWorkbenchAttributes()" in template
    assert "JSON富文本格式错误" in template
