"""
Settings 域 - 值对象。
"""
from dataclasses import dataclass, field
from typing import Optional

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class ModelConfig(ValueObject):
    """AI 模型配置"""
    id: str
    name: str
    provider: str
    base_url: str
    api_key_env: str
    model: str
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "model": self.model,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelConfig":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            provider=data.get("provider", ""),
            base_url=data.get("base_url", ""),
            api_key_env=data.get("api_key_env", ""),
            model=data.get("model", ""),
            enabled=data.get("enabled", True),
        )


@dataclass(frozen=True)
class EnvVariable(ValueObject):
    """环境变量"""
    key: str
    value: str = ""
    configured: bool = False
    masked: str = ""

    @classmethod
    def new(cls, key: str, value: str = "") -> "EnvVariable":
        configured = bool(value)
        masked = cls._mask(value) if value else ""
        return cls(key=key, value=value, configured=configured, masked=masked)

    @staticmethod
    def _mask(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "••••"
        return "••••" + value[-4:]

    @staticmethod
    def is_masked_placeholder(value: str) -> bool:
        if not value:
            return False
        return value.startswith("••") or value == "__KEEP__"


@dataclass(frozen=True)
class PricingFormula(ValueObject):
    """定价公式"""
    id: str
    platform: str
    name: str
    formula: dict = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "platform": self.platform,
            "name": self.name,
            "enabled": self.enabled,
        }
        result.update(self.formula)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "PricingFormula":
        formula_data = {k: v for k, v in data.items() if k not in ("id", "platform", "name", "enabled")}
        return cls(
            id=data.get("id", ""),
            platform=data.get("platform", ""),
            name=data.get("name", ""),
            formula=formula_data,
            enabled=data.get("enabled", True),
        )
