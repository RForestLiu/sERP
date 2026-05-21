"""
Product 域 — 产品管理（SKC/SKU/规格/图片）。

对外契约：ProductFacade ABC。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade


class ProductFacade(Facade, ABC):
    """产品域外观"""

    # ── 产品 CRUD ──

    @abstractmethod
    def list_products(self, query: str = "", platform: str = "") -> list[dict]:
        ...

    @abstractmethod
    def get_product(self, skc: str) -> dict:
        ...

    @abstractmethod
    def update_manual(self, skc: str, data: dict) -> dict:
        """手动更新产品信息"""
        ...

    @abstractmethod
    def delete_product(self, skc: str):
        ...

    # ── 规格提取 ──

    @abstractmethod
    def extract_specs(self, skc: str) -> dict:
        """收集产品规格"""
        ...

    @abstractmethod
    def auto_extract(self, skc: str) -> dict:
        """AI 自动提取产品信息"""
        ...

    @abstractmethod
    def extract_from_text(self, text: str) -> dict:
        """从文本提取产品信息"""
        ...

    # ── 图片/视频 ──

    @abstractmethod
    def get_images(self, skc: str) -> dict:
        ...

    @abstractmethod
    def get_image_sets(self, skc: str) -> dict:
        """获取图片集（按平台分组）"""
        ...

    @abstractmethod
    def update_image_sets(self, skc: str, data: dict) -> dict:
        ...

    @abstractmethod
    def upload_image(self, skc: str, file) -> dict:
        ...

    @abstractmethod
    def upload_video(self, skc: str, file) -> dict:
        ...

    @abstractmethod
    def proxy_image(self, url: str) -> bytes:
        """图片代理（绕过跨域）"""
        ...

    # ── 店铺状态 ──

    @abstractmethod
    def update_store_status(self, skc: str, data: dict) -> dict:
        """更新产品在各店铺的状态"""
        ...
