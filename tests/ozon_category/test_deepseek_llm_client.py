from src.serp.ozon_category.domain.value_objects import LLMConfig
from src.serp.ozon_category.infrastructure.llm_client import DeepSeekLLMClient


class FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"choices": [{"message": {"content": "{}"}}]}


def test_call_sends_forced_strict_tool_schema(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.serp.ozon_category.infrastructure.llm_client.requests.post", fake_post)
    client = DeepSeekLLMClient(LLMConfig(base_url="https://example.test/chat", api_key="sk-test", model="deepseek-v4-pro"))
    tool = {
        "type": "function",
        "function": {
            "name": "select_ozon_category",
            "strict": True,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }

    _, err = client.call(
        "return json",
        "pick one",
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "select_ozon_category"}},
        thinking={"type": "disabled"},
    )

    assert err == ""
    assert captured["url"] == "https://example.test/chat"
    assert captured["json"]["tools"] == [tool]
    assert captured["json"]["tool_choice"]["function"]["name"] == "select_ozon_category"
    assert captured["json"]["thinking"] == {"type": "disabled"}


def test_strict_tool_call_uses_deepseek_beta_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("src.serp.ozon_category.infrastructure.llm_client.requests.post", fake_post)
    client = DeepSeekLLMClient(LLMConfig(
        base_url="https://api.deepseek.com/v1/chat/completions",
        api_key="sk-test",
        model="deepseek-v4-flash",
    ))

    _, err = client.call(
        "return json",
        "pick one",
        tools=[{
            "type": "function",
            "function": {
                "name": "select_ozon_category",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }],
    )

    assert err == ""
    assert captured["url"] == "https://api.deepseek.com/beta/chat/completions"
