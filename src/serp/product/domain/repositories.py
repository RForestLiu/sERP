"""
Product 域 - 仓储抽象接口（DDD 端口放在 domain 层）。
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from src.serp.shared import Repository

from .entities import Product, ProductCollection


class ProductRepository(Repository[Product, str]):
    """产品聚合仓储"""

    @abstractmethod
    def load_all(self) -> ProductCollection:
        """加载全部产品"""
        ...

    @abstractmethod
    def save_collection(self, collection: ProductCollection):
        """保存全部产品集合"""
        ...

    def find_by_id(self, id: str) -> Optional[Product]:
        collection = self.load_all()
        return collection.find_by_skc(id)

    def save(self, entity: Product):
        collection = self.load_all()
        collection.add_or_update(entity)
        self.save_collection(collection)

    def delete(self, id: str):
        collection = self.load_all()
        collection.remove(id)
        self.save_collection(collection)
