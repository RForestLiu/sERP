"""
Listing 域 - 值对象。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class OzonAttribute(ValueObject):
    """Ozon 属性定义（来自品类 API）"""
    attr_id: int
    name: str = ""
    name_cn: str = ""
    description: str = ""
    attr_type: str = ""
    is_required: bool = False
    is_collection: bool = False
    max_value_count: int = 1
    dictionary_values: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.attr_id,
            "name": self.name,
            "name_cn": self.name_cn,
            "description": self.description,
            "type": self.attr_type,
            "is_required": self.is_required,
            "is_collection": self.is_collection,
            "max_value_count": self.max_value_count,
            "dictionary_values": self.dictionary_values,
        }
