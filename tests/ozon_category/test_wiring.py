from src.serp.ozon_category.domain.value_objects import LLMConfig
from src.serp.wiring import create_ozon_category_facade


class FakeEventBus:
    def subscribe(self, *_args, **_kwargs):
        pass


class FakeSettingsFacade:
    pass


def test_ozon_category_matching_uses_category_llm_feature(monkeypatch, tmp_path):
    seen = {}

    def fake_resolve_config(_settings_facade, feature_key):
        seen["feature_key"] = feature_key
        return LLMConfig(
            base_url="https://api.deepseek.com/v1/chat/completions",
            api_key="sk-test",
            model="deepseek-v4-flash",
        )

    monkeypatch.setattr(
        "src.serp.ozon_category.infrastructure.llm_client.DeepSeekLLMClient.resolve_config",
        fake_resolve_config,
    )

    create_ozon_category_facade(str(tmp_path), FakeSettingsFacade(), FakeEventBus())

    assert seen["feature_key"] == "ozon_category_match"
