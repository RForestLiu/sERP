"""
ImageTask 域 - 领域事件处理器。
"""
from __future__ import annotations

import logging

from ..domain.events import (
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

logger = logging.getLogger(__name__)


def log_task_created(event: TaskCreated):
    logger.info("Task created: %s (%s)", event.task_name, event.task_id)


def log_task_deleted(event: TaskDeleted):
    logger.info("Task deleted: %s", event.task_id)


def log_task_updated(event: TaskUpdated):
    logger.info("Task updated: %s", event.task_id)


def log_images_generated(event: ImagesGenerated):
    logger.info("Images generated for task %s: %s", event.task_id, event.count)


def log_images_saved(event: ImagesSaved):
    logger.info("Images saved for task %s: %s files", event.task_id, event.count)


def log_images_compressed(event: ImagesCompressed):
    logger.info(
        "Images compressed for task %s: %s files, saved %s bytes",
        event.task_id, event.compressed_count, event.saved_bytes,
    )


def log_source_images_uploaded(event: SourceImagesUploaded):
    logger.info("Source images uploaded for task %s: %s files", event.task_id, event.count)


def log_reference_image_uploaded(event: ReferenceImageUploaded):
    logger.info("Reference image uploaded for task %s: ref_index=%s", event.task_id, event.ref_index)


def log_images_imported(event: ImagesImported):
    logger.info("Images imported to task %s: %s files", event.task_id, event.count)


def log_images_saved_to_product(event: ImagesSavedToProduct):
    logger.info("Images saved to product for task %s: skc=%s, %s files", event.task_id, event.skc, event.count)


def log_images_copied_to_clipboard(event: ImagesCopiedToClipboard):
    logger.info("Images copied to clipboard for task %s: %s files", event.task_id, event.count)


def log_task_folder_opened(event: TaskFolderOpened):
    logger.info("Task folder opened: %s (%s)", event.task_id, event.folder)
