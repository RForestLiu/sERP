"""
OzonCategory 域 — Ozon 品类管理（品类树/翻译/AI匹配/属性）。

对外契约：OzonCategoryFacade ABC。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade


class OzonCategoryFacade(Facade, ABC):
    """Ozon 品类域外观"""

    @abstractmethod
    def get_category_tree(self, store_id: str) -> dict:
        """获取品类树（含缓存）"""
        ...

    @abstractmethod
    def translate_categories(self, store_id: str, category_ids: list[int]) -> dict:
        """批量翻译品类名（俄→中）"""
        ...

    @abstractmethod
    def refresh_categories(self, store_id: str) -> dict:
        """刷新品类树（后台异步）"""
        ...

    @abstractmethod
    def get_refresh_status(self, store_id: str) -> dict:
        """查询刷新进度"""
        ...

    @abstractmethod
    def match_category(self, store_id: str, product_info: dict) -> dict:
        """AI 匹配最合适的品类"""
        ...

    @abstractmethod
    def get_category_attributes(self, store_id: str, category_id: int) -> dict:
        """获取品类属性及字典值"""
        ...
