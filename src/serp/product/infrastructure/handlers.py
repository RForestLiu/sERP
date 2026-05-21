"""
Product 域 - 领域事件处理器。
"""
import logging

from ..domain.events import (
    ProductCreated,
    ProductDeleted,
    ProductManualUpdated,
    SpecsCollected,
    ProductAutoExtracted,
    StoreStatusChanged,
    ImageSetsUpdated,
    ProductImageUploaded,
    ProductVideoUploaded,
    ProductCriticalChangeProposed,
    ProductCriticalFieldApproved,
    ProductCriticalFieldRejected,
)

logger = logging.getLogger(__name__)


def log_product_deleted(event: ProductDeleted):
    logger.info("Product deleted: %s (%s)", event.skc, event.title)


def log_product_manual_updated(event: ProductManualUpdated):
    logger.info("Product manual updated: %s, changes=%s", event.skc, event.changes)


def log_specs_collected(event: SpecsCollected):
    logger.info("Specs collected: %s, weight=%s, size=%s", event.skc, event.weight_g, event.size_spec)


def log_product_auto_extracted(event: ProductAutoExtracted):
    logger.info("Product auto-extracted: %s, fields=%s", event.skc, event.fields)


def log_store_status_changed(event: StoreStatusChanged):
    logger.info("Store status: %s %s %s -> %s", event.skc, event.store_id, event.old_status, event.new_status)


def log_image_sets_updated(event: ImageSetsUpdated):
    logger.info("Image sets updated: %s, %s sets", event.skc, event.set_count)


def log_product_image_uploaded(event: ProductImageUploaded):
    logger.info("Image uploaded: %s -> %s/%s", event.skc, event.set_name, event.filename)


def log_product_video_uploaded(event: ProductVideoUploaded):
    logger.info("Video uploaded: %s/%s", event.skc, event.filename)


def log_critical_change_proposed(event: ProductCriticalChangeProposed):
    logger.info("Critical change proposed: %s, approval=%s, field=%s",
                event.skc, event.approval_id, event.field_name)


def log_critical_field_approved(event: ProductCriticalFieldApproved):
    logger.info("Critical field approved: %s, approval=%s, field=%s",
                event.skc, event.approval_id, event.field_name)


def log_critical_field_rejected(event: ProductCriticalFieldRejected):
    logger.info("Critical field rejected: %s, approval=%s, field=%s, reason=%s",
                event.skc, event.approval_id, event.field_name, event.reason)
