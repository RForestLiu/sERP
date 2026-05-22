"""
Settings 域 — DDD 四层架构样板。

对外暴露:
    SettingsFacade        — 域外观 ABC（公共契约）
    SettingsApplicationService — 应用服务实现
    create_settings_blueprint  — Flask 蓝图工厂
"""
from .facade import SettingsFacade
from .application import SettingsApplicationService
from .interfaces import create_settings_blueprint

# 向后兼容：旧代码引用 SettingsService 时给出明确报错
class SettingsService:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "SettingsService 已废弃，请使用 SettingsFacade。\n"
            "示例: from src.serp.settings import SettingsFacade"
        )

__all__ = [
    "SettingsFacade",
    "SettingsApplicationService",
    "create_settings_blueprint",
    "SettingsService",
]
