"""
Settings 域 - 领域事件。
"""
from dataclasses import dataclass, field

from src.serp.shared import DomainEvent


@dataclass
class SettingsUpdated(DomainEvent):
    changes: dict = field(default_factory=dict)


@dataclass
class EnvVariablesChanged(DomainEvent):
    changed_keys: list[str] = field(default_factory=list)


@dataclass
class StoreCreated(DomainEvent):
    store_id: str = ""
    store_name: str = ""


@dataclass
class StoreUpdated(DomainEvent):
    store_id: str = ""
    store_name: str = ""


@dataclass
class StoreRemoved(DomainEvent):
    store_id: str = ""
    store_name: str = ""


@dataclass
class SettingsImported(DomainEvent):
    summary: dict = field(default_factory=dict)
