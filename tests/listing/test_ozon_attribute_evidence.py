import json
from pathlib import Path

from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient


ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "mappings": [{
                            "attribute_id": 5309,
                            "value": "Нейлон",
                            "evidence": "source title says nylon wallet",
                            "reason": "material inferred from title",
                        }]
                    })
                }
            }]
        }


def read_template() -> str:
    return (ROOT / "templates" / "ozon_product_editor.html").read_text(encoding="utf-8")


def test_dynamic_attribute_area_has_right_side_evidence_panel():
    template = read_template()

    assert "margin: 0 0 0 22px;" in template
    assert "justify-content: start;" in template
    assert 'id="attr-evidence-list"' in template
    assert "function renderAttributeEvidencePanel()" in template
    assert "function formatAttributeEvidence(evidence)" in template
    assert "pageState.attributeEvidence" in template
    assert "renderAttributeEvidencePanel();" in template


def test_dianxiaomi_attribute_evidence_mounts_under_control_area():
    source = (ROOT / "extensions" / "amazon_collector" / "dianxiaomi_ozon.js").read_text(encoding="utf-8")

    assert "function fieldEvidenceMountFromEntry(entry)" in source
    assert ".ant-form-item-control, .el-form-item__content, .form-group-content" in source
    assert "data-serp-evidence-index" in source


def test_dianxiaomi_attribute_evidence_renders_when_llm_returns_no_mappings():
    source = (ROOT / "extensions" / "amazon_collector" / "dianxiaomi_ozon.js").read_text(encoding="utf-8")

    assert "var unmatchedResults = formFields.map" in source
    assert "renderProductAttributeEvidence(unmatchedResults, mappingByIndex);" in source


def test_ozon_llm_attribute_parser_keeps_evidence(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("src.serp.listing.infrastructure.autofill_client.requests.post", fake_post)
    client = DeepSeekAutoFillClient(base_url="https://example.test/chat", api_key="sk-test")

    result = client._api_call_attr("system prompt", "user prompt", label="test")

    assert result[0]["evidence"] == "source title says nylon wallet"
    assert '"evidence"' in captured["json"]["messages"][0]["content"]
