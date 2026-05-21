"""
Product 域 — 产品管理（SKC/规格/图片/视频）。

对外暴露:
    ProductFacade        — 域外观 ABC（公共契约）
    ProductApplicationService — 应用服务实现
    create_product_blueprint  — Flask 蓝图工厂（API 路由）
    create_product_static_blueprint — 静态文件蓝图（图片/视频服务）
"""
from .facade import ProductFacade
from .application import ProductApplicationService
from .interfaces import create_product_blueprint, create_product_static_blueprint

__all__ = [
    "ProductFacade",
    "ProductApplicationService",
    "create_product_blueprint",
    "create_product_static_blueprint",
]
