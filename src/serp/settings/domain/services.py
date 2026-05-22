"""
Settings 域 - 领域服务（纯业务逻辑，无 I/O 依赖）。
"""
from .entities import Store
from .value_objects import ModelConfig


FEATURE_MODEL_KEYS = {
    "image_generation": "图片生成",
    "product_collect_image_classify": "采集图片分类",
    "ozon_category_match": "Ozon 品类匹配",
    "dianxiaomi_auto_fill": "店小秘自动填充",
    "ozon_attribute_fill": "Ozon 属性填充",
    "translation": "翻译/本地化",
    "product_specs_extract": "产品重量尺提取",
    "product_specs_review": "产品重量尺审核",
}

MANAGED_ENV_KEYS = [
    "API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "IMAGE_MODEL",
    "IMAGE_SIZE",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_AUTO_FILL_MODEL",
    "DEEPSEEK_CATEGORY_MODEL",
    "DEEPSEEK_REVIEW_MODEL",
    "PROXY",
    "PROXY_ENABLED",
]

DEFAULT_SETTINGS = {
    "version": 1,
    "models": [
        {
            "id": "deepseek_v4_flash",
            "name": "DeepSeek V4 Flash",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1/chat/completions",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-v4-flash",
            "enabled": True,
        },
        {
            "id": "gemini_image",
            "name": "Gemini Image",
            "provider": "gemini",
            "base_url": "https://api.laozhang.ai/v1",
            "api_key_env": "API_KEY",
            "model": "gemini-3.1-flash-image-preview",
            "enabled": True,
        },
    ],
    "feature_models": {
        "image_generation": "gemini_image",
        "product_collect_image_classify": "deepseek_v4_flash",
        "ozon_category_match": "deepseek_v4_flash",
        "dianxiaomi_auto_fill": "deepseek_v4_flash",
        "ozon_attribute_fill": "deepseek_v4_flash",
        "translation": "deepseek_v4_flash",
        "product_specs_extract": "deepseek_v4_flash",
        "product_specs_review": "deepseek_v4_flash",
    },
    "pricing_formulas": [
        {
            "id": "ozon_rfbs_default",
            "platform": "ozon",
            "name": "Ozon rFBS default",
            "enabled": True,
            "currency": "CNY",
            "rounding": "ceil",
            "formula": "(cost_price_cny + seller_logistics_cny + ozon_fixed_fee_cny + return_reserve_cny + other_fixed_cost_cny) / (1 - profit_rate - ozon_commission_rate - acquiring_rate - promotion_rate - other_percent_fee_rate)",
            "old_price_formula": "sale_price_cny * original_price_multiplier",
            "defaults": {
                "profit_rate": 0.3,
                "ozon_commission_rate": 0.18,
                "acquiring_rate": 0.015,
                "promotion_rate": 0,
                "other_percent_fee_rate": 0,
                "seller_logistics_cny": 8.32,
                "ozon_fixed_fee_cny": 0,
                "return_reserve_cny": 0,
                "other_fixed_cost_cny": 0,
                "original_price_multiplier": 1.8,
                "stock": 10000,
                "logistics_channel": "XY Economy Extra Small",
                "chargeable_weight_mode": "actual_or_volume_12000",
            },
        },
        {
            "id": "wb_default",
            "platform": "wb",
            "name": "Wildberries default",
            "enabled": True,
            "currency": "CNY",
            "rounding": "ceil",
            "formula": "(cost_price_cny + seller_logistics_cny + platform_fixed_fee_cny + return_reserve_cny + other_fixed_cost_cny) / (1 - profit_rate - platform_commission_rate - acquiring_rate - promotion_rate - other_percent_fee_rate)",
            "old_price_formula": "sale_price_cny * original_price_multiplier",
            "defaults": {
                "profit_rate": 0.3,
                "platform_commission_rate": 0.2,
                "acquiring_rate": 0,
                "promotion_rate": 0,
                "other_percent_fee_rate": 0,
                "seller_logistics_cny": 0,
                "platform_fixed_fee_cny": 0,
                "return_reserve_cny": 0,
                "other_fixed_cost_cny": 0,
                "original_price_multiplier": 1.8,
                "stock": 10000,
            },
        },
        {
            "id": "amazon_default",
            "platform": "amazon",
            "name": "Amazon default",
            "enabled": True,
            "currency": "CNY",
            "rounding": "ceil",
            "formula": "(cost_price_cny + seller_logistics_cny + platform_fixed_fee_cny + return_reserve_cny + other_fixed_cost_cny) / (1 - profit_rate - platform_commission_rate - acquiring_rate - promotion_rate - other_percent_fee_rate)",
            "old_price_formula": "sale_price_cny * original_price_multiplier",
            "defaults": {
                "profit_rate": 0.3,
                "platform_commission_rate": 0.15,
                "acquiring_rate": 0,
                "promotion_rate": 0,
                "other_percent_fee_rate": 0,
                "seller_logistics_cny": 0,
                "platform_fixed_fee_cny": 0,
                "return_reserve_cny": 0,
                "other_fixed_cost_cny": 0,
                "original_price_multiplier": 1.8,
                "stock": 10000,
            },
        },
    ],
}


class SettingsValidationService:
    """设置验证领域服务"""

    @staticmethod
    def validate_model(model: dict) -> list[str]:
        errors = []
        if not model.get("id", "").strip():
            errors.append("模型 ID 不能为空")
        if not model.get("name", "").strip():
            errors.append("模型名称不能为空")
        return errors

    @staticmethod
    def validate_store(store_data: dict, _existing_stores: list[Store]) -> list[str]:
        errors = []
        if not store_data.get("id", "").strip():
            errors.append("店铺 ID 不能为空")
        if not store_data.get("name", "").strip():
            errors.append("店铺名称不能为空")
        return errors

    @staticmethod
    def validate_env_key(key: str) -> bool:
        return key.isidentifier()

    @staticmethod
    def extract_env_references(value: str) -> list[str]:
        import re
        refs = re.findall(r'<(\w+)>', value)
        refs += re.findall(r'env:(\w+)', value)
        return list(set(refs))

    @staticmethod
    def is_env_placeholder(value: str) -> bool:
        if not value:
            return False
        import re
        return bool(re.match(r'^<[A-Z_]+>$', value.strip()))
