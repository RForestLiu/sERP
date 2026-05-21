"""
Listing 域 - 领域事件处理器。
"""
from __future__ import annotations

import logging

from ..domain.events import (
    DraftSaved,
    DraftDeleted,
    ListingSimulated,
    ProductImportedToOzon,
    ProductsSynced,
)

logger = logging.getLogger(__name__)


def log_draft_saved(event: DraftSaved):
    logger.info("Draft saved: skc=%s store=%s", event.skc, event.store_id)


def log_draft_deleted(event: DraftDeleted):
    logger.info("Draft deleted: skc=%s store=%s", event.skc, event.store_id)


def log_listing_simulated(event: ListingSimulated):
    logger.info("Listing simulated: skc=%s store=%s score=%s can_submit=%s",
                event.skc, event.store_id, event.score, event.can_submit)


def log_product_imported(event: ProductImportedToOzon):
    logger.info("Product imported to Ozon: skc=%s store=%s task_id=%s items=%s",
                event.skc, event.store_id, event.task_id, event.item_count)


def log_products_synced(event: ProductsSynced):
    logger.info("Products synced: store=%s matched=%s updated=%s new=%s",
                event.store_id, event.matched, event.updated, event.new_skus)
