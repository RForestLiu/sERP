"""
Shared kernel — 所有域的公共基础类型和工具。
"""

from .base_value_object import ValueObject
from .base_entity import Entity
from .base_aggregate import AggregateRoot
from .base_domain_event import DomainEvent
from .base_repository import Repository
from .base_facade import Facade
from .event_bus import SyncEventBus, EventBus
from .json_store import JsonFileStore
from .result import Result
from .exceptions import DomainError, NotFoundError, ValidationError
from .di import DIContainer
from .facades import FacadeRegistry

__all__ = [
    "ValueObject",
    "Entity",
    "AggregateRoot",
    "DomainEvent",
    "Repository",
    "Facade",
    "EventBus",
    "SyncEventBus",
    "JsonFileStore",
    "Result",
    "DomainError",
    "NotFoundError",
    "ValidationError",
    "DIContainer",
    "FacadeRegistry",
]
