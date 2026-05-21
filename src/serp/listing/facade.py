"""
Listing 域 — Ozon 上架草稿与上架 API。

对外契约：ListingFacade ABC。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade


class ListingFacade(Facade, ABC):
    """上架域外观"""

    # ── 草稿管理 ──

    @abstractmethod
    def get_draft(self, skc: str, store_id: str) -> dict:
        """获取上架草稿"""
        ...

    @abstractmethod
    def save_draft(self, skc: str, store_id: str, data: dict) -> dict:
        """保存上架草稿"""
        ...

    @abstractmethod
    def delete_draft(self, skc: str, store_id: str):
        """删除上架草稿"""
        ...

    # ── Ozon 上架 API ──

    @abstractmethod
    def simulate(self, store_id: str, data: dict) -> dict:
        """模拟上架（预览）"""
        ...

    @abstractmethod
    def create_product(self, store_id: str, data: dict) -> dict:
        """正式创建商品到 Ozon"""
        ...

    @abstractmethod
    def sync_products(self, store_id: str, data: dict) -> dict:
        """同步 Ozon 在售商品"""
        ...

    # ── AI 填充 ──

    @abstractmethod
    def analyze_for_autofill(self, data: dict) -> dict:
        """分析产品数据，返回自动填充建议"""
        ...

    @abstractmethod
    def fill_ozon_fields(self, data: dict) -> dict:
        """AI 填充 Ozon 属性字段"""
        ...
