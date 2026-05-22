"""
ImageTask 域 — 图片批量处理。

对外契约：ImageTaskFacade ABC。
"""
from abc import ABC, abstractmethod

from src.serp.shared import Facade


class ImageTaskFacade(Facade, ABC):
    """图片任务域外观"""

    # ── 任务类型 ──

    @abstractmethod
    def list_task_types(self) -> list[dict]:
        """列出可用任务类型"""
        ...

    # ── 任务 CRUD ──

    @abstractmethod
    def list_tasks(self) -> list[dict]:
        ...

    @abstractmethod
    def get_task(self, task_id: str) -> dict:
        ...

    @abstractmethod
    def create_task(self, data: dict) -> dict:
        ...

    @abstractmethod
    def update_task(self, task_id: str, data: dict) -> dict:
        ...

    @abstractmethod
    def delete_task(self, task_id: str):
        ...

    # ── 图片操作 ──

    @abstractmethod
    def upload_source_images(self, task_id: str, files: list) -> dict:
        """上传源图片"""
        ...

    @abstractmethod
    def upload_ref_image(self, task_id: str, ref_index: int, file) -> dict:
        """上传参考图"""
        ...

    @abstractmethod
    def import_images(self, task_id: str, urls: list[str]) -> dict:
        """从 URL 导入图片"""
        ...

    @abstractmethod
    def generate(self, task_id: str, config: dict) -> dict:
        """AI 生成图片"""
        ...

    @abstractmethod
    def save_images(self, task_id: str, data: dict) -> dict:
        """保存生成的图片"""
        ...

    @abstractmethod
    def compress_images(self, task_id: str, config: dict) -> dict:
        """压缩图片"""
        ...

    # ── 导出 ──

    @abstractmethod
    def save_to_product(self, task_id: str, data: dict) -> dict:
        """将图片保存为产品"""
        ...

    @abstractmethod
    def copy_to_clipboard(self, task_id: str) -> dict:
        """复制图片到剪贴板"""
        ...

    @abstractmethod
    def open_folder(self, task_id: str):
        """打开任务文件夹"""
        ...
