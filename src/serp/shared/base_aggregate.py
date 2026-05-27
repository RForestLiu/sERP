"""
AggregateRoot 基类 — 聚合根，维护领域事件集合。
"""
from dataclasses import dataclass, field

from .base_entity import Entity
from .base_domain_event import DomainEvent


@dataclass
class AggregateRoot(Entity):
    """聚合根基类。收集领域事件，供应用层在持久化后发布。"""

    _domain_events: list[DomainEvent] = field(default_factory=list, repr=False, init=False)

    def add_domain_event(self, event: DomainEvent):
        self._domain_events.append(event)

    def collect_events(self) -> list[DomainEvent]:
        events = list(self._domain_events)
        self._domain_events.clear()
        return events
