"""
ImageTask 域 - 领域事件。
"""
from dataclasses import dataclass, field

from src.serp.shared import DomainEvent


@dataclass
class TaskCreated(DomainEvent):
    task_id: str = ""
    task_name: str = ""


@dataclass
class TaskDeleted(DomainEvent):
    task_id: str = ""


@dataclass
class TaskUpdated(DomainEvent):
    task_id: str = ""


@dataclass
class ImagesGenerated(DomainEvent):
    task_id: str = ""
    count: int = 0


@dataclass
class ImagesSaved(DomainEvent):
    task_id: str = ""
    count: int = 0


@dataclass
class ImagesCompressed(DomainEvent):
    task_id: str = ""
    compressed_count: int = 0
    saved_bytes: int = 0


@dataclass
class SourceImagesUploaded(DomainEvent):
    task_id: str = ""
    count: int = 0


@dataclass
class ReferenceImageUploaded(DomainEvent):
    task_id: str = ""
    ref_index: int = 0


@dataclass
class ImagesImported(DomainEvent):
    task_id: str = ""
    count: int = 0


@dataclass
class ImagesSavedToProduct(DomainEvent):
    task_id: str = ""
    skc: str = ""
    count: int = 0


@dataclass
class ImagesCopiedToClipboard(DomainEvent):
    task_id: str = ""
    count: int = 0


@dataclass
class TaskFolderOpened(DomainEvent):
    task_id: str = ""
    folder: str = ""
