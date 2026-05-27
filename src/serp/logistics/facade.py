"""
Logistics 域 — 物流模板与运费计算。

对外契约：LogisticsFacade ABC。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade


class LogisticsFacade(Facade, ABC):
    """物流域外观"""

    @abstractmethod
    def list_templates(self) -> list[dict]:
        """列出物流模板"""
        ...

    @abstractmethod
    def calculate(self, data: dict) -> dict:
        """计算运费"""
        ...
