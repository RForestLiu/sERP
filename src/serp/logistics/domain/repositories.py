"""
Logistics 域 - 仓储抽象接口。
"""
from abc import abstractmethod
from typing import Optional

from .entities import LogisticsTemplate


class LogisticsTemplateRepository:
    """物流模板仓储接口"""

    @abstractmethod
    def load_all(self) -> list[LogisticsTemplate]:
        ...

    @abstractmethod
    def find_by_id(self, template_id: str) -> Optional[LogisticsTemplate]:
        ...
