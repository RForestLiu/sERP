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

    # ── 关键属性审批 ──

    @abstractmethod
    def propose_critical_change(self, skc: str, field: str, new_value,
                                requested_by: str) -> dict:
        """提交关键属性修改申请，返回 approval_id"""
        ...

    @abstractmethod
    def approve_change(self, skc: str, approval_id: str,
                       approved_by: str) -> dict:
        """审批通过，应用修改"""
        ...

    @abstractmethod
    def reject_change(self, skc: str, approval_id: str,
                      approved_by: str, reason: str) -> dict:
        """驳回修改"""
        ...

    @abstractmethod
    def list_pending_approvals(self, skc: str = None) -> list[dict]:
        """查询待审批列表"""
        ...
