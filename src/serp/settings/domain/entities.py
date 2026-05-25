"""
Settings 域 - 实体与聚合根。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.serp.shared import AggregateRoot, Entity, DomainError

from .value_objects import ModelConfig, EnvVariable, PricingFormula


@dataclass
class Store(Entity):
    """店铺实体"""
    name: str = ""
    platform: str = ""
    client_id: str = ""
    api_key: str = ""
    client_secret: str = ""
    token: str = ""
    warehouse_id: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = self.created_at

    # ── 业务行为 ──

    def update_credentials(
        self,
        client_id: str = "",
        api_key: str = "",
        client_secret: str = "",
        token: str = "",
        warehouse_id: str = "",
    ):
        if client_id and not EnvVariable.is_masked_placeholder(client_id):
            self.client_id = client_id
        if api_key and not EnvVariable.is_masked_placeholder(api_key):
            self.api_key = api_key
        if client_secret and not EnvVariable.is_masked_placeholder(client_secret):
            self.client_secret = client_secret
        if token and not EnvVariable.is_masked_placeholder(token):
            self.token = token
        if warehouse_id and not EnvVariable.is_masked_placeholder(warehouse_id):
            self.warehouse_id = warehouse_id
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def update_info(self, name: str = "", platform: str = "", enabled: bool = None):
        if name:
            self.name = name
        if platform:
            self.platform = platform
        if enabled is not None:
            self.enabled = enabled
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def disable(self):
        self.enabled = False

    def enable(self):
        self.enabled = True

    # ── 视图 / 序列化 ──

    def to_view(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "client_id": self.client_id,
            "api_key": self._mask(self.api_key),
            "client_secret": self._mask(self.client_secret),
            "token": self._mask(self.token),
            "warehouse_id": self.warehouse_id,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "client_id": self.client_id,
            "api_key": self.api_key,
            "client_secret": self.client_secret,
            "token": self.token,
            "warehouse_id": self.warehouse_id,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Store":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            platform=data.get("platform", ""),
            client_id=data.get("client_id", ""),
            api_key=data.get("api_key", ""),
            client_secret=data.get("client_secret", ""),
            token=data.get("token", ""),
            warehouse_id=data.get("warehouse_id", ""),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    @staticmethod
    def _mask(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 4:
            return "••••"
        return "••••" + value[-4:]


@dataclass
class Settings(AggregateRoot):
    """设置聚合根"""

    _models: list[ModelConfig] = field(default_factory=list, repr=False)
    _feature_models: dict[str, str] = field(default_factory=dict, repr=False)
    _pricing_formulas: list[PricingFormula] = field(default_factory=list, repr=False)
    _product_clean_language: str = "English"
    _version: int = 1

    # ── 属性 ──

    @property
    def models(self) -> list[ModelConfig]:
        return list(self._models)

    @property
    def feature_models(self) -> dict[str, str]:
        return dict(self._feature_models)

    @property
    def pricing_formulas(self) -> list[PricingFormula]:
        return list(self._pricing_formulas)

    @property
    def product_clean_language(self) -> str:
        return self._product_clean_language

    @property
    def version(self) -> int:
        return self._version

    # ── 模型管理 ──

    def add_model(self, model: ModelConfig):
        if not model.id:
            raise DomainError("Model id is required")
        self._models = [m for m in self._models if m.id != model.id]
        self._models.append(model)

    def remove_model(self, model_id: str):
        self._models = [m for m in self._models if m.id != model_id]

    def set_feature_model(self, feature_key: str, model_id: str):
        if not feature_key:
            raise DomainError("Feature key is required")
        self._feature_models[feature_key] = model_id

    # ── 定价公式管理 ──

    def add_pricing_formula(self, formula: PricingFormula):
        if not formula.id:
            raise DomainError("Formula id is required")
        self._pricing_formulas = [f for f in self._pricing_formulas if f.id != formula.id]
        self._pricing_formulas.append(formula)

    def remove_pricing_formula(self, formula_id: str):
        self._pricing_formulas = [f for f in self._pricing_formulas if f.id != formula_id]

    # ── 批量更新 ──

    def update_from_dict(self, data: dict):
        if "models" in data:
            self._models = [ModelConfig.from_dict(m) for m in data["models"] if isinstance(m, dict)]
        if "feature_models" in data:
            self._feature_models = data["feature_models"]
        if "pricing_formulas" in data:
            self._pricing_formulas = [
                PricingFormula.from_dict(f) for f in data["pricing_formulas"] if isinstance(f, dict)
            ]
        if "product_clean_language" in data:
            self._product_clean_language = str(data.get("product_clean_language") or "English")
        if "version" in data:
            self._version = data["version"]

    def ensure_defaults(self, defaults: dict):
        model_ids = {m.id for m in self._models}
        for dm in defaults.get("models", []):
            if dm.get("id") not in model_ids:
                self._models.append(ModelConfig.from_dict(dm))
        for key, value in defaults.get("feature_models", {}).items():
            if key not in self._feature_models:
                self._feature_models[key] = value
        if not self._product_clean_language:
            self._product_clean_language = defaults.get("product_clean_language", "English")

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "version": self._version,
            "models": [m.to_dict() for m in self._models],
            "feature_models": dict(self._feature_models),
            "pricing_formulas": [f.to_dict() for f in self._pricing_formulas],
            "product_clean_language": self._product_clean_language,
        }
