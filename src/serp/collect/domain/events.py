"""
Collect 域 - 领域事件。
"""
from dataclasses import dataclass, field

from src.serp.shared import DomainEvent


@dataclass
class TaskStarted(DomainEvent):
    task_id: str = ""
    url: str = ""


@dataclass
class TaskProgressUpdated(DomainEvent):
    task_id: str = ""
    status: str = ""
    progress: int = 0


@dataclass
class TaskCompleted(DomainEvent):
    task_id: str = ""
    platform: str = ""
    title: str = ""


@dataclass
class TaskFailed(DomainEvent):
    task_id: str = ""
    error: str = ""


@dataclass
class TaskDeleted(DomainEvent):
    task_id: str = ""


@dataclass
class ProductSavedFromCollect(DomainEvent):
    task_id: str = ""
    skc: str = ""
