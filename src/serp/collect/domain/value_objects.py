"""
Collect 域 - 值对象。
"""
from dataclasses import dataclass, field
from urllib.parse import urlparse
import re

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class CollectUrl(ValueObject):
    """采集目标 URL"""
    url: str

    def __post_init__(self):
        if not self.is_valid_url(self.url):
            raise ValueError(f"Invalid collection URL: {self.url}")

    @staticmethod
    def is_valid_url(u: str) -> bool:
        if not u or not isinstance(u, str):
            return False
        return u.startswith(("http://", "https://"))

    @property
    def platform(self) -> str:
        domain = urlparse(self.url).netloc.lower()
        if "ozon" in domain:
            return "ozon"
        elif "wildberries" in domain:
            return "wildberries"
        elif "amazon" in domain:
            return "amazon"
        elif "yandex" in domain:
            return "yandex"
        elif "1688" in domain:
            return "1688"
        return "unknown"


@dataclass(frozen=True)
class TaskId(ValueObject):
    """采集任务 ID"""
    prefix: str = "collect"
    hex_part: str = ""

    @property
    def value(self) -> str:
        return f"{self.prefix}_{self.hex_part}"

    @classmethod
    def generate(cls, prefix: str = "collect", hex_part: str = "") -> "TaskId":
        import uuid
        h = hex_part or uuid.uuid4().hex[:8]
        return cls(prefix=prefix, hex_part=h)

    @classmethod
    def parse(cls, task_id: str) -> "TaskId":
        if "_" not in task_id:
            return cls(prefix="collect", hex_part=task_id)
        prefix, hex_part = task_id.split("_", 1)
        return cls(prefix=prefix, hex_part=hex_part)


@dataclass(frozen=True)
class TaskStatus(ValueObject):
    """采集任务状态"""
    status: str

    VALID_STATUSES = frozenset([
        "pending", "crawling", "classifying", "downloading",
        "saving", "completed", "error",
    ])

    def __post_init__(self):
        if self.status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid task status: {self.status}")

    @classmethod
    def pending(cls) -> "TaskStatus":
        return cls("pending")

    @classmethod
    def completed(cls) -> "TaskStatus":
        return cls("completed")

    @classmethod
    def error(cls) -> "TaskStatus":
        return cls("error")

    def is_terminal(self) -> bool:
        return self.status in ("completed", "error")

    def to_api(self) -> str:
        return self.status


PLATFORM_PREFIX = {
    "amazon": "amz",
    "1688": "1688",
    "wildberries": "wb",
    "ozon": "ozn",
}

PLATFORM_REFERER = {
    "amazon": "https://www.amazon.com/",
    "1688": "https://detail.1688.com/",
    "wildberries": "https://www.wildberries.ru/",
    "ozon": "https://www.ozon.ru/",
}


def platform_prefix(platform: str) -> str:
    """平台名 -> 任务 ID 前缀"""
    return PLATFORM_PREFIX.get(platform, "collect")


def platform_referer(platform: str) -> str:
    """平台名 -> Referer URL"""
    return PLATFORM_REFERER.get(platform, "https://www.amazon.com/")
