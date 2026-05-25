from pathlib import Path


EXTENSION_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "dianxiaomi_ozon.js"
BRIDGE_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "dxm_runtime_bridge.js"
MANIFEST_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "manifest.json"


def test_extension_collects_dianxiaomi_runtime_field_model():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function collectDxmRuntimeFieldModel()" in source
    assert "function attachDxmRuntimeMetadata(fields)" in source
    assert "function dxmComparableLabelForField(field)" in source
    assert "fieldBaseLabel(field && field.label)" in source
    assert "function isGenericDxmAttributeName(name)" in source
    assert "if (isGenericDxmAttributeName(name)) return;" in source
    assert "dxmAttribute" in source


def test_extension_sends_dxm_attribute_metadata_to_llm():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "clean.dxmAttribute" in source
    for key in ("attributeId", "dictionaryId", "collection", "required", "dxmControlKind"):
        assert key in source


def test_extension_uses_dxm_attribute_ids_for_deterministic_prefill():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function dxmAttributeIdForField(field)" in source
    assert "var attrId = dxmAttributeIdForField(f);" in source
    for attr_id in ("4383", "5299", "5355", "6573"):
        assert f'attrId === "{attr_id}"' in source


def test_extract_panel_reports_dxm_metadata_match_count():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "var dxmMatched" in source
    assert "DXM属性匹配" in source
    assert "DXM字段模型" in source
    assert "dxmRuntimeFieldCount()" in source
    assert "function dxmAttributeSummaryForField(field)" in source
    assert "dxmAttributeSummaryForField(f)" in source


def test_extract_button_is_visible_for_diagnostics():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert 'id="serp-btn-extract"' in source
    assert "#serp-toolbar #serp-btn-extract" not in source


def test_extract_panel_is_docked_to_workspace_right_side():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "#serp-extract-panel{position:fixed;left:360px;right:12px;top:86px;" in source
    assert "width:auto;max-width:none;" in source
    assert "white-space:normal;overflow:visible;text-overflow:clip;" in source
    assert 'extractPanel.style.right = "12px";' in source
    assert 'extractPanel.style.left = "360px";' in source
    assert 'extractPanel.style.top = "86px";' in source


def test_extension_bridges_page_context_for_dxm_runtime_model():
    source = EXTENSION_FILE.read_text(encoding="utf-8")
    bridge = BRIDGE_FILE.read_text(encoding="utf-8")
    manifest = MANIFEST_FILE.read_text(encoding="utf-8")

    assert "function installDxmRuntimeBridge()" in source
    assert 'chrome.runtime.getURL("dxm_runtime_bridge.js")' in source
    assert "SERP_DXM_RUNTIME_FIELD_MODEL" in source
    assert "SERP_DXM_RUNTIME_FIELD_MODEL" in bridge
    assert "window.postMessage" in bridge
    assert "window.addEventListener(\"message\"" in source
    assert "dxm_runtime_bridge.js" in manifest
    assert "web_accessible_resources" in manifest


def test_extract_diagnostics_waits_for_dxm_runtime_cache():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "async function doExtractFields()" in source
    assert "await waitForDxmRuntimeFieldModel" in source
    assert "function dxmRuntimeFieldCount()" in source
    assert "installDxmRuntimeBridge();" in source
