"""
Logistics 域 — 物流模板与运费计算。
"""
from .facade import LogisticsFacade
from .application import LogisticsApplicationService
from .interfaces import create_logistics_blueprint

__all__ = [
    "LogisticsFacade",
    "LogisticsApplicationService",
    "create_logistics_blueprint",
]
