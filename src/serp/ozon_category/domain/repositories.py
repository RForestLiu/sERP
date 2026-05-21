"""
OzonCategory 域 - 仓储抽象接口（DDD 端口放在 domain 层）。
"""
from abc import ABC, abstractmethod
from typing import Optional

from .entities import CategoryTree


class CategoryTreeCacheRepository(ABC):
    """品类树缓存仓储"""

    @abstractmethod
    def load(self, store_id: str) -> Optional[CategoryTree]:
        """加载缓存的品类树，无缓存返回 None"""
        ...

    @abstractmethod
    def save(self, store_id: str, tree: CategoryTree):
        """保存品类树到缓存"""
        ...


class TranslationCacheRepository(ABC):
    """品类名翻译缓存仓储"""

    @abstractmethod
    def load(self, store_id: str) -> dict[str, str]:
        """加载翻译缓存 {category_id_str: chinese_name}"""
        ...

    @abstractmethod
    def save(self, store_id: str, translations: dict[str, str]):
        """保存翻译缓存"""
        ...

    @abstractmethod
    def update(self, store_id: str, new_translations: dict[str, str]):
        """增量更新翻译缓存"""
        ...


class AttributeTranslationCacheRepository(ABC):
    """属性名 / 描述翻译缓存仓储"""

    @abstractmethod
    def load_names(self, store_id: str) -> dict[str, str]:
        """加载属性名翻译缓存 {russian: chinese}"""
        ...

    @abstractmethod
    def save_names(self, store_id: str, translations: dict[str, str]):
        """保存属性名翻译缓存"""
        ...

    @abstractmethod
    def load_descriptions(self, store_id: str) -> dict[str, str]:
        """加载属性描述翻译缓存"""
        ...

    @abstractmethod
    def save_descriptions(self, store_id: str, translations: dict[str, str]):
        """保存属性描述翻译缓存"""
        ...


class ExcludedCategoriesRepository(ABC):
    """无属性品类排除列表仓储"""

    @abstractmethod
    def load(self, store_id: str) -> set[int]:
        """加载排除的品类 ID 集合"""
        ...

    @abstractmethod
    def add(self, store_id: str, category_id: int):
        """添加一个品类到排除列表"""
        ...
