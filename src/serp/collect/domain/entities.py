"""
Collect 域 - 实体与聚合根。
"""
from dataclasses import dataclass, field
from datetime import datetime

from src.serp.shared import AggregateRoot, DomainError

from .value_objects import TaskId, TaskStatus


@dataclass
class CollectTask(AggregateRoot):
    """采集任务聚合根"""

    url: str = ""
    platform: str = ""
    _status: str = "pending"
    progress: int = 0
    message: str = ""
    created_at: str = ""
    source: str = "serp"

    _result: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    # ── 属性 ──

    @property
    def status(self) -> str:
        return self._status

    @property
    def result(self) -> dict:
        return dict(self._result)

    @property
    def is_terminal(self) -> bool:
        return self._status in ("completed", "error")

    @property
    def is_completed(self) -> bool:
        return self._status == "completed"

    # ── 状态机 ──

    def start(self, platform: str = ""):
        if self._status != "pending":
            raise DomainError(f"Cannot start task in status: {self._status}")
        self._status = "pending"
        self.progress = 0
        self.message = "等待开始..."
        if platform:
            self.platform = platform

    def update_progress(self, status: str, progress: int, message: str = ""):
        self._status = status
        self.progress = progress
        if message:
            self.message = message

    def complete(self, result: dict):
        self._status = "completed"
        self.progress = 100
        self._result = result
        self.message = f"采集完成！{result.get('downloaded', 0)}张图片已下载"
        self.add_domain_event(TaskCompleted(task_id=self.id, result=result))

    def fail(self, error: str):
        self._status = "error"
        self.progress = 0
        self.message = f"采集失败: {error}"
        self._result = {"task_id": self.id, "status": "error", "url": self.url, "error": error}
        self.add_domain_event(TaskFailed(task_id=self.id, error=error))

    def set_as_extension_capture(self, platform: str, title: str, image_count: int,
                                  variant_count: int = 0, source: str = "browser_extension"):
        """标记为浏览器扩展直接回传结果（已完成，无需采集引擎）"""
        self._status = "completed"
        self.progress = 100
        self.source = source
        self.platform = platform
        self.message = f"{platform} 采集 — {title[:40]}"
        if variant_count:
            self.message += f" ({variant_count}变体)"
        self._result = {
            "task_id": self.id,
            "status": "completed",
            "url": self.url,
            "platform": platform,
            "title": title,
            "image_count": image_count,
            "downloaded": 0,
            "failed": 0,
            "source": source,
        }

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "platform": self.platform,
            "status": self._status,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "source": self.source,
            "result": self._result,
        }

    def to_api(self) -> dict:
        """返回 API 摘要（列表用）"""
        r = self._result or {}
        return {
            "task_id": self.id,
            "status": self._status,
            "message": self.message,
            "url": r.get("url", self.url),
            "title": r.get("title", ""),
            "platform": r.get("platform", self.platform),
            "downloaded": r.get("downloaded", 0),
            "image_count": r.get("image_count", 0),
            "failed": r.get("failed", 0),
            "created_at": self.created_at,
        }

    def to_status(self) -> dict:
        """返回状态查询结果"""
        return {
            "task_id": self.id,
            "status": self._status,
            "progress": self.progress,
            "message": self.message,
            "result": self._result,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CollectTask":
        task = cls(
            id=data.get("id", data.get("task_id", "")),
            url=data.get("url", ""),
            platform=data.get("platform", ""),
            progress=data.get("progress", 0),
            message=data.get("message", ""),
            created_at=data.get("created_at", ""),
            source=data.get("source", "serp"),
        )
        status = data.get("status", "pending")
        object.__setattr__(task, '_status', status)
        object.__setattr__(task, '_result', data.get("result") or {})
        return task


# ── 领域事件（定义在 entities.py 以避免循环导入） ──

@dataclass
class TaskCompleted:
    task_id: str = ""
    result: dict = field(default_factory=dict)


@dataclass
class TaskFailed:
    task_id: str = ""
    error: str = ""


@dataclass
class TaskStarted:
    task_id: str = ""
    url: str = ""


@dataclass
class TaskDeleted:
    task_id: str = ""


@dataclass
class ProductSaved:
    task_id: str = ""
    skc: str = ""
