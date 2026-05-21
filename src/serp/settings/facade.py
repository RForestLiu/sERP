"""
Settings 域对外的公共接口（ABC）。
其他域通过此接口调用 Settings，不直接依赖内部实现。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade

from .application.dto import (
    SettingsViewDTO,
    SettingsExportDTO,
    ImportPreviewDTO,
    ImportResultDTO,
)


class SettingsFacade(Facade, ABC):
    """Settings 域外观 — 公共契约"""

    # ── 查询 ──

    @abstractmethod
    def get_view(self) -> SettingsViewDTO:
        ...

    @abstractmethod
    def export_payload(self, include_secrets: bool = False) -> SettingsExportDTO:
        ...

    @abstractmethod
    def get_env_status(self) -> dict:
        ...

    @abstractmethod
    def get_stores(self) -> list[dict]:
        ...

    @abstractmethod
    def get_models(self) -> list[dict]:
        ...

    @abstractmethod
    def get_feature_model(self, feature_key: str) -> str:
        """获取某功能绑定的模型ID"""
        ...

    @abstractmethod
    def get_pricing_formulas(self, platform: str = "") -> list[dict]:
        ...

    # ── 命令 ──

    @abstractmethod
    def update(self, data: dict) -> dict:
        ...

    @abstractmethod
    def preview_import(self, payload: dict) -> ImportPreviewDTO:
        ...

    @abstractmethod
    def apply_import(self, payload: dict) -> ImportResultDTO:
        ...
