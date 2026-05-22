"""
ImageTask 域 - 核心层。
"""
from .entities import ImageTask, TaskCard
from .value_objects import TaskType
from .events import (
    TaskCreated,
    TaskDeleted,
    TaskUpdated,
    ImagesGenerated,
    ImagesSaved,
    ImagesCompressed,
    SourceImagesUploaded,
    ReferenceImageUploaded,
    ImagesImported,
    ImagesSavedToProduct,
    ImagesCopiedToClipboard,
    TaskFolderOpened,
)
from .repositories import ImageTaskRepository
from .services import (
    TASK_TYPES,
    CompressImageService,
    CopyToClipboardService,
    FileManagementService,
)

__all__ = [
    "ImageTask",
    "TaskCard",
    "TaskType",
    "TaskCreated",
    "TaskDeleted",
    "TaskUpdated",
    "ImagesGenerated",
    "ImagesSaved",
    "ImagesCompressed",
    "SourceImagesUploaded",
    "ReferenceImageUploaded",
    "ImagesImported",
    "ImagesSavedToProduct",
    "ImagesCopiedToClipboard",
    "TaskFolderOpened",
    "ImageTaskRepository",
    "TASK_TYPES",
    "CompressImageService",
    "CopyToClipboardService",
    "FileManagementService",
]
