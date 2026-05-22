"""
DomainEvent 基类 — 所有领域事件的基类。
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DomainEvent:
    """领域事件基类"""
    occurred_at: str = field(default_factory=lambda: datetime.now().isoformat(), init=False)
