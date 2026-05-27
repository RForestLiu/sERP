"""
Logistics 域 - 核心层。
"""
from .entities import LogisticsTemplate
from .value_objects import ChannelConfig, ParcelSpec, MatchedChannel
from .services import ChannelMatchingService
from .repositories import LogisticsTemplateRepository

__all__ = [
    "LogisticsTemplate",
    "ChannelConfig",
    "ParcelSpec",
    "MatchedChannel",
    "ChannelMatchingService",
    "LogisticsTemplateRepository",
]
