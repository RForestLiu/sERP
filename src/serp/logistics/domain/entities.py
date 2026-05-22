"""
Logistics 域 - 实体。
"""
from dataclasses import dataclass, field

from src.serp.shared import Entity

from .value_objects import ChannelConfig


@dataclass
class LogisticsTemplate(Entity):
    """物流模板 — 含多个物流渠道配置"""
    name: str = ""
    description: str = ""
    default_for_ozon: bool = False
    channels: list[ChannelConfig] = field(default_factory=list)

    @property
    def channel_count(self) -> int:
        return len(self.channels)

    def to_summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "default_for_ozon": self.default_for_ozon,
            "channel_count": self.channel_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticsTemplate":
        channels = [
            ChannelConfig.from_dict(ch) for ch in data.get("channels", [])
            if isinstance(ch, dict)
        ]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            default_for_ozon=data.get("default_for_ozon", False),
            channels=channels,
        )
