"""
Settings 域 - 核心层。
"""
from .entities import Store, Settings
from .value_objects import ModelConfig, EnvVariable, PricingFormula
from .services import (
    SettingsValidationService,
    FEATURE_MODEL_KEYS,
    MANAGED_ENV_KEYS,
    DEFAULT_SETTINGS,
)
from .events import (
    SettingsUpdated,
    EnvVariablesChanged,
    StoreCreated,
    StoreUpdated,
    StoreRemoved,
    SettingsImported,
)
from .repositories import SettingsRepository, StoreRepository, EnvRepository

__all__ = [
    "Store",
    "Settings",
    "ModelConfig",
    "EnvVariable",
    "PricingFormula",
    "SettingsValidationService",
    "FEATURE_MODEL_KEYS",
    "MANAGED_ENV_KEYS",
    "DEFAULT_SETTINGS",
    "SettingsUpdated",
    "EnvVariablesChanged",
    "StoreCreated",
    "StoreUpdated",
    "StoreRemoved",
    "SettingsImported",
    "SettingsRepository",
    "StoreRepository",
    "EnvRepository",
]
