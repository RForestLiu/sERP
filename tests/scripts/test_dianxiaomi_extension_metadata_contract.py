from pathlib import Path


EXTENSION_FILE = Path(__file__).resolve().parents[2] / "extensions" / "amazon_collector" / "dianxiaomi_ozon.js"


def test_extension_collects_dianxiaomi_runtime_field_model():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "function collectDxmRuntimeFieldModel()" in source
    assert "function attachDxmRuntimeMetadata(fields)" in source
    assert "dxmAttribute" in source


def test_extension_sends_dxm_attribute_metadata_to_llm():
    source = EXTENSION_FILE.read_text(encoding="utf-8")

    assert "clean.dxmAttribute" in source
    for key in ("attributeId", "dictionaryId", "collection", "required", "dxmControlKind"):
        assert key in source
