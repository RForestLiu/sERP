import json

import requests

from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient


def test_form_field_summary_includes_dianxiaomi_runtime_metadata():
    fields = [{
        "index": 7,
        "label": "Material",
        "tag": "select",
        "type": "select",
        "controlKind": "ant-select-search",
        "dxmAttribute": {
            "sourceGroup": "attrsList",
            "attributeId": "5309",
            "name": "Material",
            "nameCn": "Material",
            "type": "String",
            "collection": 1,
            "required": 1,
            "dictionaryId": "321",
            "optionsNum": 100,
            "maxValueCount": 3,
            "dxmControlKind": "dictionary-multiple-remote",
        },
    }]

    summary, _, _ = DeepSeekAutoFillClient._build_form_fields_summary(fields)

    assert "DXM" in summary
    assert "5309" in summary
    assert "dictionary-multiple-remote" in summary
    assert "321" in summary


def test_form_field_summary_includes_dxm_dictionary_options():
    fields = [{
        "index": 4,
        "label": "Country of origin",
        "tag": "select",
        "type": "select",
        "dxmAttribute": {
            "attributeId": "4389",
            "name": "Strana-izgotovitel",
            "nameCn": "Country of origin",
            "dictionaryId": "1935",
            "dxmControlKind": "dictionary-single",
            "options": [
                {"id": "90296", "value": "Kitay", "valueCn": "China", "valueEn": "China"},
                {"id": "90295", "value": "Rossiya", "valueCn": "Russia", "valueEn": "Russia"},
            ],
        },
    }]

    summary, _, _ = DeepSeekAutoFillClient._build_form_fields_summary(fields)

    assert "DXM" in summary
    assert "90296" in summary
    assert "China(Kitay)" in summary
    assert "dictionary_value_id" in summary


def test_api_call_preserves_dictionary_id_and_evidence(monkeypatch):
    client = DeepSeekAutoFillClient(api_key="key", base_url="https://example.test/v1")

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "mappings": [{
                                "index": 4,
                                "value": "Kitay",
                                "dictionary_value_id": "90296",
                                "evidence": "origin country from product data",
                                "reason": "country field",
                                "confidence": 0.91,
                                "needs_review": False,
                            }]
                        })
                    }
                }]
            }

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: FakeResponse())

    mappings = client._api_call("system", "user")

    assert mappings == [{
        "index": 4,
        "label": "",
        "value": "Kitay",
        "dictionary_value_id": "90296",
        "evidence": "origin country from product data",
        "reason": "country field",
        "confidence": 0.91,
        "needs_review": False,
    }]
