"""
Collect 域 — 多平台商品采集。

对外契约：CollectFacade ABC。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade


class CollectFacade(Facade, ABC):
    """采集域外观"""

    # ── 任务管理 ──

    @abstractmethod
    def list_tasks(self) -> list[dict]:
        """列出所有采集任务"""
        ...

    @abstractmethod
    def start(self, url: str, platform: str = "") -> dict:
        """启动采集，返回 {task_id, ...}"""
        ...

    @abstractmethod
    def get_status(self, task_id: str) -> dict:
        """查询采集进度"""
        ...

    @abstractmethod
    def get_result(self, task_id: str) -> dict:
        """获取采集结果"""
        ...

    @abstractmethod
    def clean_product_data(self, task_id: str, force: bool = False) -> dict:
        """Start LLM cleaning for a collected product."""
        ...

    @abstractmethod
    def cancel_product_clean(self, task_id: str) -> dict:
        """Cancel an in-progress product data cleaning job."""
        ...

    @abstractmethod
    def delete_task(self, task_id: str):
        """删除采集任务及其数据"""
        ...

    # ── 产品化 ──

    @abstractmethod
    def get_product_status(self, task_id: str) -> dict:
        """查询采集数据是否已转为产品"""
        ...

    @abstractmethod
    def save_to_product(self, task_id: str) -> dict:
        """将采集数据保存为正式产品，返回 {skc, ...}"""
        ...

    # ── 各平台采集入口 ──

    @abstractmethod
    def capture_amazon(self, url: str, html: str, settings: dict) -> dict:
        """Amazon 捕获（来自浏览器扩展）"""
        ...

    @abstractmethod
    def capture_browser(self, html: str, url: str) -> dict:
        """通用浏览器捕获"""
        ...

    @abstractmethod
    def capture_dxm(self, data: dict, store_id: str) -> dict:
        """店小秘捕获"""
        ...

    @abstractmethod
    def save_html(self, html: str, url: str) -> dict:
        """保存 HTML 快照"""
        ...
