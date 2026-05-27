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

    @abstractmethod
    def auto_category(self, store_id: str, data: dict) -> dict:
        """Workbench: 自动匹配 Ozon 类目"""
        ...

    @abstractmethod
    def generate_workbench_draft(self, store_id: str, data: dict) -> dict:
        """Workbench: 生成可验证的 Ozon 草稿"""
        ...

    @abstractmethod
    def validate_workbench_payload(self, store_id: str, data: dict) -> dict:
        """Workbench: 程序验证 Ozon 草稿"""
        ...

    @abstractmethod
    def prepare_images(self, store_id: str, data: dict) -> dict:
        """Workbench: 准备可提交的图片 URL"""
        ...

    @abstractmethod
    def upsert_workbench(self, store_id: str, data: dict) -> dict:
        """Workbench: 批量上架/更新"""
        ...

    @abstractmethod
    def official_rating(self, store_id: str, data: dict) -> dict:
        """Workbench: 查询 Ozon 官方内容评分"""
        ...

    # ── Ozon 导入状态 ──

    @abstractmethod
    def check_import_status(self, store_id: str, task_id: str) -> dict:
        """查询 Ozon 导入任务状态，返回按 offer_id 分组的 error/warning"""
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
