"""
FacadeRegistry — 域外观注册表，主 agent 通过此表管理所有域的 Facade。
"""
from typing import Optional

from .base_facade import Facade


class FacadeRegistry:
    """域外观注册表。主 agent 创建并注册所有 Facade 实例。

    用法:
        registry = FacadeRegistry()
        registry.register("settings", settings_facade)
        settings = registry.get("settings")
    """

    def __init__(self):
        self._facades: dict[str, Facade] = {}

    def register(self, name: str, facade: Facade):
        if name in self._facades:
            raise KeyError(f"Facade '{name}' already registered")
        self._facades[name] = facade

    def get(self, name: str) -> Optional[Facade]:
        return self._facades.get(name)

    def get_required(self, name: str) -> Facade:
        facade = self._facades.get(name)
        if not facade:
            raise KeyError(f"Facade '{name}' not found. Available: {list(self._facades.keys())}")
        return facade

    def list_names(self) -> list[str]:
        return list(self._facades.keys())
