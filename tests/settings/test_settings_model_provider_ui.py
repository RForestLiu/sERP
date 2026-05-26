from pathlib import Path


def test_settings_models_are_grouped_by_provider_channel():
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert "function groupModelProviders" in template
    assert "function flattenModelProviders" in template
    assert "settings-provider-card" in template
    assert "data-channel-field=\"api_key_env\"" in template
    assert "同一通道下所有模型共用这个密钥" in template
    assert 'document.querySelectorAll("#settings-models-list .settings-provider-card")' in template


def test_settings_page_exposes_product_clean_prompt_editor():
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert "data-product-clean-prompt" in template
    assert "settings-reset-clean-prompt" in template
    assert "恢复默认提示词" in template
    assert "product_clean_default_prompt" in template
