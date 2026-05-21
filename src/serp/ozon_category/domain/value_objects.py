"""
OzonCategory 域 - 值对象。
"""
from dataclasses import dataclass, field

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class LLMConfig(ValueObject):
    """LLM 调用配置"""
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_settings_facade(cls, settings_facade, feature_key: str, env_model_key: str, default_model: str) -> "LLMConfig":
        """从 SettingsFacade 解析 LLM 配置（跟随 settings 域模型选择）"""
        import os
        base_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        model = os.getenv(env_model_key, default_model)

        try:
            model_id = settings_facade.get_feature_model(feature_key)
            models = settings_facade.get_models()
            for m in models:
                if m.get("id") == model_id:
                    base_url = m.get("base_url") or base_url
                    model = m.get("model") or model
                    api_key_env = m.get("api_key_env") or "DEEPSEEK_API_KEY"
                    api_key = os.getenv(api_key_env, api_key)
                    break
        except Exception:
            pass

        return cls(base_url=base_url, api_key=api_key, model=model)


@dataclass(frozen=True)
class TranslationEntry(ValueObject):
    """翻译条目"""
    cid: str  # 品类 ID（字符串形式统一处理）
    name_ru: str
    name_cn: str = ""


@dataclass(frozen=True)
class AttributeDefinition(ValueObject):
    """Ozon 属性定义"""
    attr_id: int
    name: str
    description: str = ""
    attr_type: str = ""
    is_required: bool = False
    is_collection: bool = False
    max_value_count: int = 1
    dictionary_values: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.attr_id,
            "name": self.name,
            "description": self.description,
            "type": self.attr_type,
            "is_required": self.is_required,
            "is_collection": self.is_collection,
            "max_value_count": self.max_value_count,
            "dictionary_values": self.dictionary_values,
        }
