"""
ImageTask 域 - 仓储抽象接口（DDD 归属：端口放在 domain 层）。
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from src.serp.shared import Repository

from .entities import ImageTask


class ImageTaskRepository(Repository[ImageTask, str]):
    """图片任务聚合仓储"""

    @abstractmethod
    def load_all(self) -> list[ImageTask]:
        ...

    @abstractmethod
    def save_all(self, tasks: list[ImageTask]):
        ...

    @abstractmethod
    def load(self, task_id: str) -> Optional[ImageTask]:
        ...

    def find_by_id(self, id: str) -> Optional[ImageTask]:
        return self.load(id)

    def save(self, entity: ImageTask):
        """保存单个任务（含摘要和详细数据）"""
        tasks = self.load_all()
        found = False
        for i, t in enumerate(tasks):
            if t.id == entity.id:
                tasks[i] = entity
                found = True
                break
        if not found:
            tasks.append(entity)
        self.save_all(tasks)

    def delete(self, task_id: str):
        tasks = [t for t in self.load_all() if t.id != task_id]
        self.save_all(tasks)

    @abstractmethod
    def ensure_dirs(self, task_id: str):
        """确保任务目录结构存在"""
        ...

    @abstractmethod
    def delete_task_directory(self, task_id: str):
        """删除任务文件目录"""
        ...

    @abstractmethod
    def task_folder(self, task_id: str) -> str:
        """获取任务目录路径"""
        ...

    @abstractmethod
    def get_generated_files(self, task_id: str, include_drafts: bool = False) -> list[str]:
        """获取生成图片文件列表"""
        ...

    @abstractmethod
    def move_drafts_to_generated(self, task_id: str) -> list[str]:
        """把 drafts 目录中的文件移到 generated 目录，返回移动的文件名列表"""
        ...

    @abstractmethod
    def save_uploaded_file(self, task_id: str, file_data, filename: str) -> str:
        """保存上传的文件到 source_images 目录，返回相对路径"""
        ...

    @abstractmethod
    def save_ref_image(self, task_id: str, ref_index: int, file_data) -> str:
        """保存参考图，返回相对路径"""
        ...

    @abstractmethod
    def import_product_images(self, task_id: str, images_dir: str, filenames: list[str]) -> list[dict]:
        """从产品图片目录导入文件到任务 source_images 目录"""
        ...
