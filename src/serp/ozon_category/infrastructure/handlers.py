"""
OzonCategory 域 - 领域事件处理器。
"""
import logging

from ..domain.events import (
    CategoryTreeFetched,
    CategoriesTranslated,
    CategoriesRefreshed,
    CategoryMatchCompleted,
)

logger = logging.getLogger(__name__)


def log_category_tree_fetched(event: CategoryTreeFetched):
    logger.info("[OzonCategory] 品类树获取: store=%s, nodes=%s", event.store_id, event.node_count)


def log_categories_translated(event: CategoriesTranslated):
    logger.info("[OzonCategory] 品类翻译: store=%s, %s/%s", event.store_id, event.translated_count, event.total)


def log_categories_refreshed(event: CategoriesRefreshed):
    logger.info("[OzonCategory] 品类刷新: store=%s, nodes=%s, translated=%s, %.1fs",
                event.store_id, event.total_nodes, event.translated, event.elapsed_seconds)


def log_category_match_completed(event: CategoryMatchCompleted):
    logger.info("[OzonCategory] 品类匹配: store=%s, 产品=%s → %s(%s), %.1fs",
                event.store_id, event.product_title[:50], event.matched_category,
                event.matched_category_id, event.elapsed_seconds)
