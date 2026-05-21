"""
OzonCategory 域 — DDD 四层架构。

对外暴露:
    OzonCategoryFacade              — 域外观 ABC（公共契约）
    OzonCategoryApplicationService  — 应用服务实现
    create_ozon_category_blueprint  — Flask 蓝图工厂
"""
from .facade import OzonCategoryFacade
from .application import OzonCategoryApplicationService
from .interfaces import create_ozon_category_blueprint

__all__ = [
    "OzonCategoryFacade",
    "OzonCategoryApplicationService",
    "create_ozon_category_blueprint",
]
