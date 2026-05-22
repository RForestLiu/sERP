"""
Collect 域 - JSON 文件仓储实现。
"""
import json
import os
import logging
from typing import Optional

from src.serp.shared import JsonFileStore

from ..domain.entities import CollectTask
from ..domain.repositories import CollectTaskRepository

logger = logging.getLogger(__name__)


class JsonCollectTaskRepository(CollectTaskRepository):
    """JSON 文件采集任务仓储 — 内存 + 持久化"""

    def __init__(self, filepath: str):
        self._store = JsonFileStore(filepath)
        self._tasks: dict[str, CollectTask] = {}
        self._load_persisted()

    def _load_persisted(self):
        """启动时加载持久化的任务（仅已完成的/出错的）"""
        data = self._store.read()
        if not data:
            return
        for tid, tdata in data.items():
            if isinstance(tdata, dict) and tdata.get("status") in ("completed", "error"):
                task = CollectTask.from_dict(dict(task_id=tid, **tdata))
                self._tasks[tid] = task

    def load_all(self) -> dict[str, CollectTask]:
        return dict(self._tasks)

    def save(self, task: CollectTask):
        self._tasks[task.id] = task

    def save_all(self):
        """持久化已完成的/出错的任务"""
        saved = {}
        for tid, task in self._tasks.items():
            if task.is_terminal:
                saved[tid] = {
                    "status": task.status,
                    "progress": task.progress,
                    "message": task.message,
                    "result": task.result,
                    "url": task.url,
                    "platform": task.platform,
                    "created_at": task.created_at,
                    "source": task.source,
                }
        self._store.write(saved)

    def find_by_id(self, task_id: str) -> Optional[CollectTask]:
        return self._tasks.get(task_id)

    def delete(self, task_id: str):
        self._tasks.pop(task_id, None)
        self.save_all()

    def list_completed(self) -> list[CollectTask]:
        return [t for t in self._tasks.values() if t.status in ("completed", "error")]
