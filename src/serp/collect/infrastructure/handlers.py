"""
Collect 域 - 领域事件处理器。
订阅事件总线中的事件，执行副作用（日志等）。
"""
import logging

from ..domain.events import (
    TaskStarted,
    TaskProgressUpdated,
    TaskCompleted as TaskCompletedEvent,
    TaskFailed as TaskFailedEvent,
    TaskDeleted as TaskDeletedEvent,
    ProductSavedFromCollect,
)

logger = logging.getLogger(__name__)


def log_task_started(event: TaskStarted):
    logger.info("Collect task started: %s -> %s", event.task_id, event.url)


def log_task_progress_updated(event: TaskProgressUpdated):
    logger.info("Collect task %s: %s (%d%%)", event.task_id, event.status, event.progress)


def log_task_completed(event: TaskCompletedEvent):
    logger.info("Collect task completed: %s (%s - %s)", event.task_id, event.platform, event.title)


def log_task_failed(event: TaskFailedEvent):
    logger.error("Collect task failed: %s — %s", event.task_id, event.error)


def log_task_deleted(event: TaskDeletedEvent):
    logger.info("Collect task deleted: %s", event.task_id)


def log_product_saved_from_collect(event: ProductSavedFromCollect):
    logger.info("Product saved from collect: %s -> %s", event.task_id, event.skc)
