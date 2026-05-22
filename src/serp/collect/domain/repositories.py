"""
Collect 域 - 仓储抽象接口。
"""
from abc import abstractmethod
from typing import Optional

from src.serp.shared import Repository

from .entities import CollectTask


class CollectTaskRepository(Repository[CollectTask, str]):
    """采集任务仓储"""

    @abstractmethod
    def load_all(self) -> dict[str, CollectTask]:
        """加载所有任务（keyed by task_id）"""
        ...

    @abstractmethod
    def save(self, task: CollectTask):
        """保存单个任务"""
        ...

    @abstractmethod
    def save_all(self):
        """持久化所有运行中任务"""
        ...

    @abstractmethod
    def find_by_id(self, task_id: str) -> Optional[CollectTask]:
        ...

    @abstractmethod
    def delete(self, task_id: str):
        """删除任务（从内存和持久化中移除）"""
        ...

    @abstractmethod
    def list_completed(self) -> list[CollectTask]:
        """列出已完成/出错的任务"""
        ...
