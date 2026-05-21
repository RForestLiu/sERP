"""
Product 域 - JSON 文件仓储实现。
"""
from __future__ import annotations

import os
import logging
from threading import RLock
from typing import Optional

from src.serp.shared import JsonFileStore

from ..domain.entities import Product, ProductCollection
from ..domain.repositories import ProductRepository

logger = logging.getLogger(__name__)


class JsonProductRepository(ProductRepository):
    """JSON 文件产品仓储 — 线程安全"""

    def __init__(self, filepath: str):
        self._store = JsonFileStore(filepath)
        self._lock = RLock()

    def load_all(self) -> ProductCollection:
        with self._lock:
            data = self._store.read_any()
            if data is None:
                return ProductCollection()
            return ProductCollection.from_dict(data)

    def save_collection(self, collection: ProductCollection):
        with self._lock:
            self._store.write(collection.to_dict())

    def find_by_id(self, id: str) -> Optional[Product]:
        collection = self.load_all()
        return collection.find_by_skc(id)

    def save(self, entity: Product):
        """保存单个产品（加载 → 更新 → 写回）"""
        with self._lock:
            collection = self.load_all()
            collection.add_or_update(entity)
            self._store.write(collection.to_dict())

    def delete(self, id: str):
        with self._lock:
            collection = self.load_all()
            collection.remove(id)
            self._store.write(collection.to_dict())
