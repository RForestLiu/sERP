"""
Listing 域 - 领域事件。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.serp.shared import DomainEvent


@dataclass
class DraftSaved(DomainEvent):
    skc: str = ""
    store_id: str = ""


@dataclass
class DraftDeleted(DomainEvent):
    skc: str = ""
    store_id: str = ""


@dataclass
class ListingSimulated(DomainEvent):
    skc: str = ""
    store_id: str = ""
    score: int = 0
    can_submit: bool = False


@dataclass
class ProductImportedToOzon(DomainEvent):
    skc: str = ""
    store_id: str = ""
    task_id: str = ""
    item_count: int = 0
    score: int = 0
    error: str = ""
    event: str = ""


@dataclass
class ProductsSynced(DomainEvent):
    store_id: str = ""
    matched: int = 0
    updated: int = 0
    new_skus: int = 0
