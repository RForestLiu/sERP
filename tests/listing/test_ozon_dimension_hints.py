import json

from src.serp.listing.domain.services import DeterministicPreFiller
from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient


class FakeResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"choices": [{"message": {"content": json.dumps({"mappings": []})}}]}


def test_deterministic_prefiller_converts_labeled_inches_dimensions():
    hints = DeterministicPreFiller.extract(
        {},
        {"product_details": {"item_dimensions_d_x_w_x_h": '6.8"D x 3.1"W x 8.6"H'}},
    )

    assert hints["size_spec"] == "17.3x7.9x21.8cm"
    assert hints["size_source"] == "product_details.item_dimensions_d_x_w_x_h"


def test_ozon_attribute_prompt_includes_product_details_dimensions(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["prompt"] = json["messages"][1]["content"]
        return FakeResponse()

    monkeypatch.setattr("src.serp.listing.infrastructure.autofill_client.requests.post", fake_post)
    client = DeepSeekAutoFillClient(base_url="https://example.test/chat", api_key="sk-test")

    client.fill_ozon_attributes(
        skc="HATS-0001",
        product_title="Mesh shower caddy",
        product_data={"product_details": {"item_dimensions_d_x_w_x_h": '6.8"D x 3.1"W x 8.6"H'}},
        manual_data={},
        ozon_attributes=[{"id": 5299, "name": "Высота", "type": "String", "is_required": True}],
    )

    assert 'item_dimensions_d_x_w_x_h' in captured["prompt"]
    assert "6.8" in captured["prompt"]
    assert "3.1" in captured["prompt"]
    assert "8.6" in captured["prompt"]
    assert "17.3x7.9x21.8cm" in captured["prompt"]
    assert "manual_data 优先级高于采集数据" in captured["prompt"]


def test_ozon_attribute_prompt_includes_full_product_data(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["prompt"] = json["messages"][1]["content"]
        return FakeResponse()

    monkeypatch.setattr("src.serp.listing.infrastructure.autofill_client.requests.post", fake_post)
    client = DeepSeekAutoFillClient(base_url="https://example.test/chat", api_key="sk-test")

    client.fill_ozon_attributes(
        skc="HATS-0001",
        product_title="Mesh shower caddy",
        product_data={
            "title": "Mesh shower caddy",
            "custom_collected_block": {"rare_key": "rare collected value"},
            "variantData": {"black": {"inventory_hint": "full product data marker"}},
        },
        manual_data={},
        ozon_attributes=[{"id": 5299, "name": "Высота", "type": "String", "is_required": True}],
    )

    assert "### 完整产品数据" in captured["prompt"]
    assert "custom_collected_block" in captured["prompt"]
    assert "rare collected value" in captured["prompt"]
    assert "variantData" in captured["prompt"]
    assert "full product data marker" in captured["prompt"]
