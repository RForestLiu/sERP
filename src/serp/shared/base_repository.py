"""
Repository 抽象基类 — 定义仓储的通用接口。
"""
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional

T = TypeVar("T")
ID = TypeVar("ID")


class Repository(ABC, Generic[T, ID]):
    """仓储抽象基类。各域在 domain/repositories.py 中继承并定义本域仓储接口。"""

    @abstractmethod
    def find_by_id(self, id: ID) -> Optional[T]:
        ...

    @abstractmethod
    def save(self, entity: T):
        ...

    @abstractmethod
    def delete(self, id: ID):
        ...
