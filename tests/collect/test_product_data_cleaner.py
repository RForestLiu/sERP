import json

from src.serp.collect.infrastructure.product_data_cleaner import ProductDataCleaner


class FakeSettings:
    def __init__(self, language=""):
        self.language = language

    def get_feature_model(self, feature_key):
        assert feature_key == "product_data_clean"
        return "deepseek_v4_pro"

    def get_models(self):
        return [{
            "id": "deepseek_v4_pro",
            "base_url": "https://example.test/chat",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-v4-pro",
        }]

    def get_view(self):
        return type("View", (), {"settings": {"product_clean_language": self.language}})()


def test_cleaner_preserves_raw_and_splits_parameters_descriptions(monkeypatch):
    calls = []

    def fake_post(_url, headers, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            content = {
                "product_param": [
                    {"key": "product_weight", "value": "200g", "evidence": "product_details.weight"},
                    {"key": "product_size", "value": "10x5x3cm", "evidence": "product_details.size"},
                ],
                "product_description": {
                    "summary": "Compact daily wallet.",
                    "evidence": ["about_item", "product_description"],
                },
            }
        else:
            content = {
                "passed": True,
                "issues": [],
                "checks": [
                    {"field": "product_weight", "result": "pass", "evidence": "product_details.weight"}
                ],
            }
        return type("Resp", (), {
            "status_code": 200,
            "text": "ok",
            "json": lambda self: {
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "function": {
                                "name": json["tool_choice"]["function"]["name"],
                                "arguments": json_module.dumps(content, ensure_ascii=False),
                            },
                        }],
                    },
                }],
            },
        })()

    json_module = json
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("src.serp.collect.infrastructure.product_data_cleaner.requests.post", fake_post)

    raw = {
        "title": "Wallet",
        "product_details": {"weight": "200g", "size": "10x5x3cm"},
        "about_item": "Daily wallet.",
        "product_description": "Subjective copy.",
    }

    cleaned = ProductDataCleaner(FakeSettings()).clean(raw)

    assert cleaned["raw_product_data"] == raw
    assert cleaned["product_data"] == {
        "product_param": {"product_weight": "200g", "product_size": "10x5x3cm"},
        "product_description": "Compact daily wallet.",
    }
    assert cleaned["clean_audit"]["model"] == "deepseek-v4-pro"
    assert cleaned["clean_audit"]["language"] == "English"
    assert cleaned["clean_audit"]["evidence"]["product_weight"] == "product_details.weight"
    assert cleaned["clean_audit"]["review"]["passed"] is True
    assert calls[0]["model"] == "deepseek-v4-pro"
    assert calls[0]["tools"][0]["function"]["strict"] is True
    assert calls[0]["tool_choice"]["function"]["name"] == "clean_product_data"
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_cleaner_routes_strict_tools_to_deepseek_beta(monkeypatch):
    urls = []

    def fake_post(url, headers, json, timeout):
        urls.append(url)
        content = {
            "product_param": [],
            "product_description": {"summary": "", "evidence": []},
        }
        if json["tool_choice"]["function"]["name"] == "audit_product_data":
            content = {"passed": True, "issues": [], "checks": []}
        return type("Resp", (), {
            "status_code": 200,
            "text": "ok",
            "json": lambda self: {
                "choices": [{
                    "message": {
                        "tool_calls": [{
                            "function": {"arguments": json_module.dumps(content, ensure_ascii=False)},
                        }],
                    },
                }],
            },
        })()

    json_module = json
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    monkeypatch.setattr("src.serp.collect.infrastructure.product_data_cleaner.requests.post", fake_post)

    class EnvSettings(FakeSettings):
        def get_models(self):
            return []

    ProductDataCleaner(EnvSettings()).clean({"title": "Wallet"})

    assert urls == [
        "https://api.deepseek.com/beta/chat/completions",
        "https://api.deepseek.com/beta/chat/completions",
    ]


def test_cleaner_reports_empty_structured_output(monkeypatch):
    def fake_post(_url, headers, json, timeout):
        return type("Resp", (), {
            "status_code": 200,
            "text": "ok",
            "json": lambda self: {"choices": [{"message": {"content": ""}}]},
        })()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("src.serp.collect.infrastructure.product_data_cleaner.requests.post", fake_post)

    cleaned = ProductDataCleaner(FakeSettings()).clean({"product_details": {"weight": "200g"}})

    assert cleaned["clean_audit"]["status"] == "failed"
    assert "empty structured output" in cleaned["clean_audit"]["error"]


def test_cleaner_falls_back_when_llm_is_not_configured(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    raw = {
        "product_details": {"weight": "200g"},
        "about_item": "About text.",
        "product_description": "Description text.",
    }

    cleaned = ProductDataCleaner(FakeSettings()).clean(raw)

    assert cleaned["raw_product_data"] == raw
    assert cleaned["product_data"] == {
        "product_param": {"weight": "200g"},
        "product_description": "About text.\nDescription text.",
    }
    assert cleaned["clean_audit"]["status"] == "failed"
    assert "DEEPSEEK_API_KEY" in cleaned["clean_audit"]["error"]
