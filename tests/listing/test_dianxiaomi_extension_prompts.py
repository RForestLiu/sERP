from pathlib import Path


def test_extension_exposes_grouped_autofill_prompt_inputs():
    source = Path("extensions/amazon_collector/dianxiaomi_ozon.js").read_text(encoding="utf-8")

    assert "serp-hint-product-fields" in source
    assert "serp-hint-title" in source
    assert "serp-hint-desc" in source
    assert "serp-hint-json" in source
    assert "serp-hint-hashtag" in source
    assert "serp-hint-variant" in source
    assert "platform_prompt" in source
    assert "serp_hint_store_" in source
    assert "serp_hint_category_" in source
    assert "prompts.product_fields" in source
    assert "prompts.variant" in source


def test_extension_exposes_default_prompt_actions():
    source = Path("extensions/amazon_collector/dianxiaomi_ozon.js").read_text(encoding="utf-8")

    assert "DEFAULT_HINT_PROMPTS" in source
    assert "data-default-prompt=\"title\"" in source
    assert "data-default-prompt=\"product_fields\"" in source
    assert "applyDefaultHintPrompt" in source
    assert "默认提示词" in source
