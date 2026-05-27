"""
EventBus — 进程内同步事件总线。
"""
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Callable, Any
import logging

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], None]


class EventBus(ABC):
    """事件总线抽象接口"""

    @abstractmethod
    def subscribe(self, event_type: type, handler: EventHandler):
        ...

    @abstractmethod
    def publish(self, event: object):
        ...


class SyncEventBus(EventBus):
    """同步事件总线 — 发布事件时立即调用所有订阅处理器。"""

    def __init__(self):
        self._handlers: dict[type, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: EventHandler):
        self._handlers[event_type].append(handler)

    def publish(self, event: object):
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error("Event handler %s failed for %s: %s", handler.__name__, event_type.__name__, e)

    def publish_all(self, events: list[object]):
        """批量发布事件"""
        for event in events:
            self.publish(event)
