"""
OzonCategory 域 - 核心层。
"""
from .entities import CategoryNode, CategoryTree
from .value_objects import LLMConfig, TranslationEntry, AttributeDefinition
from .services import TranslationService, CategoryMatchingService
from .events import (
    CategoryTreeFetched,
    CategoriesTranslated,
    CategoriesRefreshed,
    CategoryMatchCompleted,
)
from .repositories import (
    CategoryTreeCacheRepository,
    TranslationCacheRepository,
    AttributeTranslationCacheRepository,
    ExcludedCategoriesRepository,
)

__all__ = [
    "CategoryNode",
    "CategoryTree",
    "LLMConfig",
    "TranslationEntry",
    "AttributeDefinition",
    "TranslationService",
    "CategoryMatchingService",
    "CategoryTreeFetched",
    "CategoriesTranslated",
    "CategoriesRefreshed",
    "CategoryMatchCompleted",
    "CategoryTreeCacheRepository",
    "TranslationCacheRepository",
    "AttributeTranslationCacheRepository",
    "ExcludedCategoriesRepository",
]
