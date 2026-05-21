"""
Settings 域 - 仓储抽象接口（DDD 归属：端口放在 domain 层）。
"""
from abc import abstractmethod
from typing import Optional

from src.serp.shared import Repository

from .entities import Settings, Store
from .value_objects import EnvVariable


class SettingsRepository(Repository[Settings, str]):
    """设置聚合仓储"""

    @abstractmethod
    def load(self) -> Settings:
        ...

    @abstractmethod
    def save(self, settings: Settings):
        ...

    def find_by_id(self, id: str) -> Optional[Settings]:
        return self.load()

    def delete(self, id: str):
        raise NotImplementedError("Settings aggregate cannot be deleted")


class StoreRepository(Repository[Store, str]):
    """店铺仓储"""

    @abstractmethod
    def load_all(self) -> list[Store]:
        ...

    @abstractmethod
    def save_all(self, stores: list[Store]):
        ...

    def save(self, entity: Store):
        self.save_all([entity])

    def delete(self, id: str):
        stores = [s for s in self.load_all() if s.id != id]
        self.save_all(stores)


class EnvRepository:
    """环境变量仓储（非实体仓储，不继承 Repository）"""

    @abstractmethod
    def read_all(self) -> dict[str, str]:
        ...

    @abstractmethod
    def write(self, updates: dict[str, str]):
        ...

    @abstractmethod
    def read_managed(self) -> list[EnvVariable]:
        ...
