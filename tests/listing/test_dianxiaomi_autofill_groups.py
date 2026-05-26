import json

from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient


def test_dianxiaomi_fields_are_grouped_for_separate_llm_dialogs():
    fields = [
        {"index": 1, "label": "商品重量，克 (Вес товара, г)"},
        {"index": 2, "label": "#主题标签 (#Хештеги)"},
        {"index": 3, "label": "产品标题"},
        {"index": 4, "label": "产品描述"},
        {"index": 5, "label": "JSON富文本", "type": "json-editor"},
        {"index": 6, "label": "SKU [红色(красный)]"},
        {"index": 7, "label": "售价 CNY [红色(красный)]"},
    ]

    grouped = {
        key: [field["index"] for field in group_fields]
        for key, _label, group_fields in DeepSeekAutoFillClient._group_dianxiaomi_fields(fields)
    }

    assert grouped["product_fields"] == [1]
    assert grouped["hashtag"] == [2]
    assert grouped["title"] == [3]
    assert grouped["description"] == [4]
    assert grouped["json_text"] == [5]
    assert grouped["variant"] == [6, 7]


def test_dianxiaomi_autofill_calls_once_per_non_empty_group(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "label": json["messages"][1]["content"], "model": json["model"]})
        content = {"mappings": [{"index": len(calls), "value": f"value-{len(calls)}"}]}
        return type("Resp", (), {
            "status_code": 200,
            "text": "ok",
            "json": lambda self: {"choices": [{"message": {"content": json_module.dumps(content)}}]},
        })()

    json_module = json
    monkeypatch.setattr("src.serp.listing.infrastructure.autofill_client.requests.post", fake_post)
    client = DeepSeekAutoFillClient("https://api.laozhang.ai/v1", "sk-test", "gpt-5.4-mini")

    result = client.analyze_dianxiaomi(
        skc="SKU1",
        product_title="Wallet",
        product_data={"product_details": {"weight": "100g"}},
        manual_data={},
        form_fields=[
            {"index": 10, "label": "商品重量，克 (Вес товара, г)"},
            {"index": 20, "label": "#主题标签 (#Хештеги)"},
            {"index": 30, "label": "产品标题"},
            {"index": 40, "label": "产品描述"},
            {"index": 50, "label": "JSON富文本", "type": "json-editor"},
            {"index": 60, "label": "SKU [红色(красный)]"},
        ],
        custom_prompts={"product_fields": "PF prompt", "platform": "Platform prompt"},
        variant_list=[],
        variant_row_summary={},
    )

    assert len(calls) == 6
    assert {call["url"] for call in calls} == {"https://api.laozhang.ai/v1/chat/completions"}
    assert all(call["model"] == "gpt-5.4-mini" for call in calls)
    assert len(result) == 6
    assert any("PF prompt" in call["label"] for call in calls)
    assert any("Platform prompt" in call["label"] for call in calls)


def test_product_fields_group_default_prompt_is_generated_from_current_fields():
    fields = [
        {"index": 1, "label": "配套 (Комплектация)"},
        {"index": 2, "label": "保修期 (Гарантийный срок)"},
        {"index": 3, "label": "原产国 (Страна-изготовитель) (可选值: 中国(Китай) / 俄罗斯(Россия))"},
    ]

    assert DeepSeekAutoFillClient._build_default_product_fields_prompt(fields) == (
        "配套 (Комплектация):\n"
        "保修期 (Гарантийный срок):\n"
        "原产国 (Страна-изготовитель):"
    )
