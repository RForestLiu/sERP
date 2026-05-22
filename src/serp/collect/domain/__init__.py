"""
Collect 域 - 核心层。
"""
from .entities import CollectTask, TaskCompleted, TaskFailed, TaskDeleted, ProductSaved
from .value_objects import CollectUrl, TaskId, TaskStatus, platform_prefix, platform_referer
from .services import CategorizationService, UrlService, CATEGORY_CODES, CATEGORY_KEYWORDS
from .events import (
    TaskStarted,
    TaskProgressUpdated,
    TaskCompleted as TaskCompletedEvent,
    TaskFailed as TaskFailedEvent,
    TaskDeleted as TaskDeletedEvent,
    ProductSavedFromCollect,
)
from .repositories import CollectTaskRepository

__all__ = [
    "CollectTask",
    "CollectUrl",
    "TaskId",
    "TaskStatus",
    "CategorizationService",
    "UrlService",
    "CATEGORY_CODES",
    "CATEGORY_KEYWORDS",
    "platform_prefix",
    "platform_referer",
    "TaskStarted",
    "TaskProgressUpdated",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "TaskDeletedEvent",
    "ProductSavedFromCollect",
    "CollectTaskRepository",
    "TaskCompleted",
    "TaskFailed",
    "TaskDeleted",
    "ProductSaved",
]
