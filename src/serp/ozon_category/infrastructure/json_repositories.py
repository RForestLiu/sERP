"""
OzonCategory 域 - JSON 文件仓储实现（缓存持久化）。
"""
import json
import logging
import os
import threading
from typing import Optional

from src.serp.shared import JsonFileStore

from ..domain.entities import CategoryTree
from ..domain.repositories import (
    CategoryTreeCacheRepository,
    TranslationCacheRepository,
    AttributeTranslationCacheRepository,
    ExcludedCategoriesRepository,
)

logger = logging.getLogger(__name__)


class JsonCategoryTreeCacheRepository(CategoryTreeCacheRepository):
    """JSON 文件品类树缓存仓储"""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._lock = threading.Lock()

    def _filepath(self, store_id: str) -> str:
        return os.path.join(self._cache_dir, f"{store_id}_category_tree.json")

    def load(self, store_id: str) -> Optional[CategoryTree]:
        store = JsonFileStore(self._filepath(store_id))
        data = store.read_any()
        if data is None:
            return None
        if isinstance(data, list):
            return CategoryTree.from_api_result(store_id, data)
        return None

    def save(self, store_id: str, tree: CategoryTree):
        with self._lock:
            store = JsonFileStore(self._filepath(store_id))
            store.write_list(tree.to_dict())


class JsonTranslationCacheRepository(TranslationCacheRepository):
    """JSON 文件翻译缓存仓储"""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._lock = threading.Lock()

    def _filepath(self, store_id: str) -> str:
        return os.path.join(self._cache_dir, f"{store_id}_translations.json")

    def load(self, store_id: str) -> dict[str, str]:
        store = JsonFileStore(self._filepath(store_id))
        data = store.read()
        if data is None:
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, store_id: str, translations: dict[str, str]):
        with self._lock:
            store = JsonFileStore(self._filepath(store_id))
            store.write(translations)

    def update(self, store_id: str, new_translations: dict[str, str]):
        current = self.load(store_id)
        current.update(new_translations)
        self.save(store_id, current)


class JsonAttributeTranslationCacheRepository(AttributeTranslationCacheRepository):
    """JSON 文件属性名/描述翻译缓存仓储"""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._lock = threading.Lock()

    def _names_path(self, store_id: str) -> str:
        return os.path.join(self._cache_dir, f"{store_id}_attr_translations.json")

    def _descs_path(self, store_id: str) -> str:
        return os.path.join(self._cache_dir, f"{store_id}_attr_desc_translations.json")

    def load_names(self, store_id: str) -> dict[str, str]:
        store = JsonFileStore(self._names_path(store_id))
        data = store.read()
        return data if isinstance(data, dict) else {}

    def save_names(self, store_id: str, translations: dict[str, str]):
        with self._lock:
            store = JsonFileStore(self._names_path(store_id))
            store.write(translations)

    def load_descriptions(self, store_id: str) -> dict[str, str]:
        store = JsonFileStore(self._descs_path(store_id))
        data = store.read()
        return data if isinstance(data, dict) else {}

    def save_descriptions(self, store_id: str, translations: dict[str, str]):
        with self._lock:
            store = JsonFileStore(self._descs_path(store_id))
            store.write(translations)


class JsonExcludedCategoriesRepository(ExcludedCategoriesRepository):
    """JSON 文件排除品类列表仓储"""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._lock = threading.Lock()

    def _filepath(self, store_id: str) -> str:
        return os.path.join(self._cache_dir, f"{store_id}_excluded_categories.json")

    def load(self, store_id: str) -> set[int]:
        store = JsonFileStore(self._filepath(store_id))
        data = store.read_any()
        if data is None:
            return set()
        if isinstance(data, list):
            return set(data)
        return set()

    def add(self, store_id: str, category_id: int):
        with self._lock:
            excluded = self.load(store_id)
            excluded.add(category_id)
            store = JsonFileStore(self._filepath(store_id))
            store.write_list(sorted(list(excluded)))
            logger.info("[排除品类] 品类 %s 已标记为排除", category_id)
