"""
ImageTask 域 - 值对象。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class TaskType(ValueObject):
    """任务类型"""
    id: str
    name: str
    icon: str
    description: str
    available: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
            "available": self.available,
        }
