"""
Entity 基类 — 有唯一标识的可变对象，按ID判等。
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Entity:
    """实体基类。所有域实体继承此类。"""

    id: str = ""

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return False
        if not self.id or not other.id:
            return self is other
        return self.id == other.id
