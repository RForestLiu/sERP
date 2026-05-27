"""
Settings 域 - 应用层 DTO。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SettingsViewDTO:
    """设置视图 DTO"""
    models: list[dict] = field(default_factory=list)
    feature_models: dict[str, str] = field(default_factory=dict)
    pricing_formulas: list[dict] = field(default_factory=list)
    product_clean_language: str = "English"
    product_clean_prompt: str = ""
    product_clean_default_prompt: str = ""
    env: dict[str, dict] = field(default_factory=dict)
    stores: list[dict] = field(default_factory=list)
    feature_model_keys: dict[str, str] = field(default_factory=dict)


@dataclass
class SettingsExportDTO:
    """设置导出 DTO"""
    settings: dict = field(default_factory=dict)
    stores: list[dict] = field(default_factory=list)
    env: dict[str, dict] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class ImportPreviewDTO:
    """导入预览 DTO"""
    models_diff: dict = field(default_factory=dict)
    feature_models_diff: dict = field(default_factory=dict)
    pricing_formulas_diff: dict = field(default_factory=dict)
    stores_diff: dict = field(default_factory=dict)
    env_diff: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)


@dataclass
class ImportResultDTO:
    """导入结果 DTO"""
    success: bool = True
    summary: dict = field(default_factory=dict)
    restart_required: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class SettingsUpdateDTO:
    """设置更新 DTO"""
    models: Optional[list[dict]] = None
    feature_models: Optional[dict[str, str]] = None
    pricing_formulas: Optional[list[dict]] = None
    product_clean_language: Optional[str] = None
    product_clean_prompt: Optional[str] = None
    stores: Optional[list[dict]] = None
    env: Optional[dict[str, str]] = None
