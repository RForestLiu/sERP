"""
OzonCategory 域 - 领域事件。
"""
from dataclasses import dataclass, field

from src.serp.shared import DomainEvent


@dataclass
class CategoryTreeFetched(DomainEvent):
    """品类树从 API 获取成功"""
    store_id: str = ""
    node_count: int = 0


@dataclass
class CategoriesTranslated(DomainEvent):
    """品类翻译完成"""
    store_id: str = ""
    translated_count: int = 0
    total: int = 0


@dataclass
class CategoriesRefreshed(DomainEvent):
    """品类树刷新完成（含翻译）"""
    store_id: str = ""
    total_nodes: int = 0
    translated: int = 0
    elapsed_seconds: float = 0


@dataclass
class CategoryMatchCompleted(DomainEvent):
    """品类匹配完成"""
    store_id: str = ""
    product_title: str = ""
    matched_category: str = ""
    matched_category_id: int = 0
    elapsed_seconds: float = 0
