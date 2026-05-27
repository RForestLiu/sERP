"""
Product 域 - 领域事件。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.serp.shared import DomainEvent


@dataclass
class ProductCreated(DomainEvent):
    skc: str = ""
    title: str = ""


@dataclass
class ProductDeleted(DomainEvent):
    skc: str = ""
    title: str = ""


@dataclass
class ProductManualUpdated(DomainEvent):
    skc: str = ""
    changes: dict = field(default_factory=dict)


@dataclass
class SpecsCollected(DomainEvent):
    skc: str = ""
    weight_g: str = ""
    size_spec: str = ""


@dataclass
class ProductAutoExtracted(DomainEvent):
    skc: str = ""
    fields: list[str] = field(default_factory=list)


@dataclass
class StoreStatusChanged(DomainEvent):
    skc: str = ""
    store_id: str = ""
    old_status: str = ""
    new_status: str = ""


@dataclass
class ImageSetsUpdated(DomainEvent):
    skc: str = ""
    set_count: int = 0


@dataclass
class ProductImageUploaded(DomainEvent):
    skc: str = ""
    filename: str = ""
    set_name: str = ""


@dataclass
class ProductVideoUploaded(DomainEvent):
    skc: str = ""
    filename: str = ""


@dataclass
class ProductCriticalChangeProposed(DomainEvent):
    skc: str = ""
    approval_id: str = ""
    field_name: str = ""


@dataclass
class ProductCriticalFieldApproved(DomainEvent):
    skc: str = ""
    approval_id: str = ""
    field_name: str = ""


@dataclass
class ProductCriticalFieldRejected(DomainEvent):
    skc: str = ""
    approval_id: str = ""
    field_name: str = ""
    reason: str = ""
