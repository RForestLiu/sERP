from pathlib import Path


EXTENSION_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "dianxiaomi_ozon.js"
BRIDGE_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "dxm_runtime_bridge.js"
MANIFEST_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "manifest.json"
EXPECTED_EXTENSION_VERSION = "3.2.44"


def test_extension_collects_dianxiaomi_runtime_field_model():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function collectDxmRuntimeFieldModel()" in source
    assert "function attachDxmRuntimeMetadata(fields)" in source
    assert "function dxmComparableLabelForField(field)" in source
    assert "function dxmComparableLabelPartsForField(field)" in source
    assert "labelParts.indexOf(name) !== -1" in source
    assert "fieldBaseLabel(field && field.label)" in source
    assert "function isGenericDxmAttributeName(name)" in source
    assert "if (isGenericDxmAttributeName(name)) return;" in source
    assert "material|\\u043C\\u0430\\u0442\\u0435\\u0440\\u0438\\u0430\\u043B" in source
    assert "dxmAttribute" in source


def test_extension_sends_dxm_attribute_metadata_to_llm():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "clean.dxmAttribute" in source
    for key in ("attributeId", "dictionaryId", "collection", "required", "dxmControlKind", "descriptionCategoryId", "typeId"):
        assert key in source


def test_extension_sends_dxm_runtime_options_to_llm():
    source = EXTENSION_FILE.read_text(encoding="utf-8")
    bridge = BRIDGE_FILE.read_text(encoding="utf-8")

    assert "function compactDxmOptions" in source
    assert "function compactDxmOptions" in bridge
    assert "_allOptions" in source
    assert "_options" in source
    assert "options: compactDxmOptions(attr)" in source
    assert "options: compactDxmOptions(attr)" in bridge
    assert "valueCn" in source
    assert "valueEn" in source


def test_extension_uses_dxm_dictionary_runtime_fill_path():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function fillDxmDictionaryField" in source
    assert "entry.dxmAttribute" in source
    assert "dxmAttribute: f.dxmAttribute || null" in source
    assert "dictionary_value_id" in source
    assert "fillDxmDictionaryField(entry, value)" in source
    assert "productAttrsData" in source
    assert "mergeAttrsData" in source
    assert "ozonProductBasicStore" in source
    assert "ozonProductStore" in source
    assert "return false;" in source


def test_extension_does_not_fallback_to_clicking_dxm_dictionary_selects():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    dictionary_branch = source.split('if (entry.renderMode === "AntSelect") {', 1)[1].split("// ===== select =====", 1)[0]

    assert "fillDxmDictionaryField(entry, value)" in dictionary_branch
    assert "return false;" in dictionary_branch
    assert "if (fillDxmDictionaryField(entry, value)) return true;\n          return false;" in dictionary_branch
    assert "fillAntSelect(el, value, entry.label)" not in dictionary_branch


def test_extension_does_not_click_dxm_dictionary_checkbox_groups():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    checkbox_branch = source.split("// ===== checkbox", 1)[1].split("// ===== radio", 1)[0]

    assert "isDxmDictionaryField" in source
    assert "fillDxmDictionaryField(entry, value)" in checkbox_branch
    assert "if (fillDxmDictionaryField(entry, value)) return true;\n          return false;" in checkbox_branch
    assert checkbox_branch.index("return false;") < checkbox_branch.index("fillSearchableCheckboxGroup(entry, value)")


def test_extension_does_not_click_antselect_fallback_in_autofill():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    dictionary_branch = source.split('if (entry.renderMode === "AntSelect") {', 1)[1].split("// ===== select =====", 1)[0]

    assert "fillDxmDictionaryField(entry, value)" in dictionary_branch
    assert "下拉缺少DXM候选，已跳过点击兜底" in source
    assert "fillAntSelect(el, value, entry.label)" not in dictionary_branch


def test_extension_reports_dxm_candidate_mismatch_error():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "_lastFillError" in source
    assert "DXM候选不包含该值" in source
    assert "preEntry._lastFillError" in source


def test_extension_version_is_bumped():
    source = EXTENSION_FILE.read_text(encoding="utf-8")
    manifest = MANIFEST_FILE.read_text(encoding="utf-8")

    assert f'var SERP_EXTENSION_VERSION = "{EXPECTED_EXTENSION_VERSION}";' in source
    assert f'"version": "{EXPECTED_EXTENSION_VERSION}"' in manifest


def test_extension_reports_unknown_dxm_controls_with_repro_context():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function reportUnknownDxmControls(fields)" in source
    assert 'UNKNOWN_DXM_CONTROL_STORAGE_KEY = "serp_unknown_dxm_controls"' in source
    assert "collectUnknownDxmControls(fields)" in source
    assert "chrome.storage.local.set(kv" in source
    assert "platform: detectPlatform()" in source
    assert "store_id: detectStoreId()" in source
    assert "category_path: detectOzonCategoryPathText()" in source
    assert "category_context: collectDxmCategoryContext()" in source
    assert "window.alert" in source
    assert "发现未知DXM控件" in source

    collect_tail = source.split("attachDxmRuntimeMetadata(fields);", 1)[1].split("return fields;", 1)[0]
    assert "reportUnknownDxmControls(fields)" in collect_tail


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
    assert "descriptionCategoryId" in bridge
    assert "typeId" in bridge
    assert "fieldCategory.descriptionCategoryId" in bridge
    assert "fieldCategory.typeId" in bridge


def test_extension_sends_category_context_to_autofill_api():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function collectDxmCategoryContext()" in source
    assert "store_id: detectStoreId()" in source
    assert "category_context: collectDxmCategoryContext()" in source
    assert "fieldCategory.descriptionCategoryId" in source
    assert "fieldCategory.typeId" in source


def test_extract_diagnostics_waits_for_dxm_runtime_cache():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "async function doExtractFields()" in source
    assert "await waitForDxmRuntimeFieldModel" in source
    assert "function dxmRuntimeFieldCount()" in source
    assert "installDxmRuntimeBridge();" in source


def test_auto_fill_waits_for_dynamic_variant_fields_before_llm_request():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "async function waitForStableFormFields(formFields, timeoutMs)" in source
    assert "formFields = await waitForStableFormFields(formFields, 3500);" in source
    assert "markAutoFill(\"recollect-after-variants\")" in source


def test_variant_row_context_ignores_validation_messages():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function isInvalidRowContextText(txt)" in source
    assert "最低价|售价|原价|不能" in source
    assert "!isInvalidRowContextText(txt)" in source
    assert "!isInvalidRowContextText(rowText)" in source


def test_pricing_formula_supports_minimum_price_profit_rate():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "min_profit_rate: 0.2" in source
    assert "min_price_cny" in source
    assert "profit_rate: ctx.vars.min_profit_rate" in source
    assert 'priceVarInputV2("min_profit_rate"' in source
    assert 'return "min";' in source
