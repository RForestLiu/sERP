"""
Collect 域 — 多平台商品采集。

对外暴露:
    CollectFacade        — 域外观 ABC（公共契约）
    CollectApplicationService — 应用服务实现
    create_collect_blueprint  — Flask 蓝图工厂
"""
from .facade import CollectFacade
from .application.commands import CollectApplicationService
from .interfaces.routes import create_collect_blueprint

__all__ = [
    "CollectFacade",
    "CollectApplicationService",
    "create_collect_blueprint",
]
