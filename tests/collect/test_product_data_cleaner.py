import json

from src.serp.collect.infrastructure.product_data_cleaner import ChatCompletionEndpoint, ProductDataCleaner


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


class LaoZhangCleanSettings(FakeSettings):
    def get_feature_model(self, feature_key):
        assert feature_key == "product_data_clean"
        return "laozhang_gpt_5_4_mini"

    def get_models(self):
        return [{
            "id": "laozhang_gpt_5_4_mini",
            "base_url": "https://api.laozhang.ai/v1",
            "api_key_env": "API_KEY",
            "model": "gpt-5.4-mini",
        }]


def test_cleaner_preserves_raw_and_splits_parameters_descriptions(monkeypatch):
    calls = []

    def fake_post(_url, headers, json, timeout):
        calls.append(json)
        tool_name = json["tool_choice"]["function"]["name"]
        if tool_name == "clean_product_data":
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
    assert cleaned["clean_audit"]["review"]["skipped"] is True
    assert calls[0]["model"] == "deepseek-v4-pro"
    assert calls[0]["tools"][0]["function"]["strict"] is True
    assert calls[0]["tool_choice"]["function"]["name"] == "clean_product_data"
    assert calls[0]["thinking"] == {"type": "disabled"}


def test_cleaner_can_use_laozhang_openai_compatible_model(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.setdefault("urls", []).append(url)
        captured["authorization"] = headers["Authorization"]
        captured.setdefault("models", []).append(json["model"])
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
    monkeypatch.setenv("API_KEY", "sk-laozhang")
    monkeypatch.setattr("src.serp.collect.infrastructure.product_data_cleaner.requests.post", fake_post)

    ProductDataCleaner(LaoZhangCleanSettings()).clean({"title": "Wallet"})

    assert captured["urls"] == ["https://api.laozhang.ai/v1/chat/completions"]
    assert captured["models"] == ["gpt-5.4-mini"]
    assert captured["authorization"] == "Bearer sk-laozhang"


def test_cleaner_appends_chat_completions_for_openai_compatible_base_url():
    assert ChatCompletionEndpoint("https://api.laozhang.ai/v1").request_url([]) == (
        "https://api.laozhang.ai/v1/chat/completions"
    )


def test_chat_completion_endpoint_routes_deepseek_strict_tools_to_beta():
    tools = [{"function": {"strict": True}}]

    assert ChatCompletionEndpoint("https://api.deepseek.com/v1/chat/completions").request_url(tools) == (
        "https://api.deepseek.com/beta/chat/completions"
    )


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

    assert urls == ["https://api.deepseek.com/beta/chat/completions"]


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


def test_cleaner_skips_local_language_audit_for_model_output_review(monkeypatch):
    calls = []

    def fake_post(_url, headers, json, timeout):
        calls.append(json)
        if json["tool_choice"]["function"]["name"] == "clean_product_data":
            content = {
                "product_param": [
                    {"key": "color", "value": "красный", "evidence": "product_details.color"},
                    {"key": "material", "value": "натуральная кожа", "evidence": "product_details.material"},
                ],
                "product_description": {
                    "summary": "Кошелек женский из натуральной кожи.",
                    "evidence": ["product_description"],
                },
            }
        else:
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
    monkeypatch.setattr("src.serp.collect.infrastructure.product_data_cleaner.requests.post", fake_post)

    cleaned = ProductDataCleaner(FakeSettings()).clean({
        "product_details": {"color": "красный", "material": "натуральная кожа"},
        "product_description": "Кошелек женский из натуральной кожи.",
    })

    assert cleaned["clean_audit"]["status"] == "ok"
    assert cleaned["clean_audit"]["review"]["passed"] is True
    assert cleaned["clean_audit"]["review"]["skipped"] is True
    assert "color" in cleaned["product_data"]["product_param"]
    assert len(calls) == 1


def test_cleaner_does_not_retry_after_language_mismatch_while_audit_is_skipped(monkeypatch):
    clean_calls = 0
    user_prompts = []

    def fake_post(_url, headers, json, timeout):
        nonlocal clean_calls
        tool_name = json["tool_choice"]["function"]["name"]
        user_prompts.append(json["messages"][1]["content"])
        if tool_name == "clean_product_data":
            clean_calls += 1
            if clean_calls == 1:
                content = {
                    "product_param": [
                        {"key": "color", "value": "泻褉邪褋薪褘泄", "evidence": "product_details.color"},
                    ],
                    "product_description": {"summary": "袣芯褕械谢械泻.", "evidence": ["product_description"]},
                }
            else:
                content = {
                    "product_param": [
                        {"key": "color", "value": "red", "evidence": "product_details.color"},
                    ],
                    "product_description": {"summary": "Women's leather wallet.", "evidence": ["product_description"]},
                }
        else:
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
    monkeypatch.setattr("src.serp.collect.infrastructure.product_data_cleaner.requests.post", fake_post)

    cleaned = ProductDataCleaner(FakeSettings()).clean({
        "product_details": {"color": "泻褉邪褋薪褘泄"},
        "product_description": "袣芯褕械谢械泻.",
    })

    assert cleaned["clean_audit"]["status"] == "ok"
    assert cleaned["clean_audit"]["review"]["skipped"] is True
    assert "color" in cleaned["product_data"]["product_param"]
    assert cleaned["product_data"]["product_description"]
    assert clean_calls == 1
    assert all("previous_attempt_failed" not in prompt for prompt in user_prompts)


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
