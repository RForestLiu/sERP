from src.serp.settings.domain.services import DEFAULT_SETTINGS, PRODUCT_CLEAN_DEFAULT_PROMPT


def test_default_pricing_formulas_include_minimum_profit_rate():
    formulas = DEFAULT_SETTINGS["pricing_formulas"]

    assert formulas
    for formula in formulas:
        assert formula["defaults"]["min_profit_rate"] == 0.2


def test_product_data_clean_defaults_to_laozhang_gpt_5_4_mini():
    models = {model["id"]: model for model in DEFAULT_SETTINGS["models"]}

    assert DEFAULT_SETTINGS["feature_models"]["product_data_clean"] == "laozhang_gpt_5_4_mini"
    assert models["laozhang_gpt_5_4_mini"] == {
        "id": "laozhang_gpt_5_4_mini",
        "name": "LaoZhang GPT-5.4 Mini",
        "provider": "laozhang",
        "base_url": "https://api.laozhang.ai/v1",
        "api_key_env": "API_KEY",
        "model": "gpt-5.4-mini",
        "enabled": True,
    }


def test_default_product_clean_prompt_removes_brand_content():
    assert DEFAULT_SETTINGS["product_clean_prompt"] == PRODUCT_CLEAN_DEFAULT_PROMPT
    assert "Remove brand-related content" in PRODUCT_CLEAN_DEFAULT_PROMPT
    assert "Do not mention the source product brand" in PRODUCT_CLEAN_DEFAULT_PROMPT
