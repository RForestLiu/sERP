"""
Settings 域 - JSON 文件仓储实现。
"""
import json
import os
import logging
from typing import Optional

from src.serp.shared import JsonFileStore

from ..domain.entities import Settings as SettingsAggregate, Store
from ..domain.value_objects import EnvVariable
from ..domain.services import DEFAULT_SETTINGS, MANAGED_ENV_KEYS
from ..domain.repositories import SettingsRepository, StoreRepository, EnvRepository

logger = logging.getLogger(__name__)


class JsonSettingsRepository(SettingsRepository):
    """JSON 文件设置仓储"""

    def __init__(self, filepath: str):
        self._store = JsonFileStore(filepath)

    def load(self) -> SettingsAggregate:
        settings = SettingsAggregate()
        settings.ensure_defaults(DEFAULT_SETTINGS)

        data = self._store.read()
        if data is None:
            return settings

        settings.update_from_dict(data)
        settings.ensure_defaults(DEFAULT_SETTINGS)
        return settings

    def save(self, settings: SettingsAggregate):
        self._store.write(settings.to_dict())


class JsonStoreRepository(StoreRepository):
    """JSON 文件店铺仓储"""

    def __init__(self, filepath: str):
        self._store = JsonFileStore(filepath)

    def load_all(self) -> list[Store]:
        data = self._store.read_list()
        if data is None:
            return []
        return [Store.from_dict(item) for item in data if isinstance(item, dict)]

    def save_all(self, stores: list[Store]):
        self._store.write_list([s.to_dict() for s in stores])

    def find_by_id(self, store_id: str) -> Optional[Store]:
        stores = self.load_all()
        for store in stores:
            if store.id == store_id:
                return store
        return None


class DotEnvRepository(EnvRepository):
    """.env 文件环境变量仓储"""

    def __init__(self, filepath: str):
        self._filepath = filepath

    def read_all(self) -> dict[str, str]:
        env = {}
        if not os.path.exists(self._filepath):
            return env
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.rstrip("\n")
                    stripped = raw.strip()
                    if not stripped or stripped.startswith("#") or "=" not in raw:
                        continue
                    key, value = raw.split("=", 1)
                    env[key.strip()] = value.strip().strip('"').strip("'")
        except OSError:
            pass
        return env

    def write(self, updates: dict[str, str]):
        runtime_updates = dict(updates)
        existing_lines = []
        existing_keys = set()
        if os.path.exists(self._filepath):
            try:
                with open(self._filepath, "r", encoding="utf-8") as f:
                    existing_lines = f.read().splitlines()
            except OSError:
                existing_lines = []

            for line in existing_lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in line:
                    key = line.split("=", 1)[0].strip()
                    existing_keys.add(key)

        new_lines = []
        for line in existing_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}")
                    del updates[key]
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        for key, value in updates.items():
            new_lines.append(f"{key}={value}")

        with open(self._filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines).rstrip("\n") + "\n")

        for key, value in runtime_updates.items():
            os.environ[str(key)] = str(value)

    def read_managed(self) -> list[EnvVariable]:
        all_env = self.read_all()
        result = []
        for key in MANAGED_ENV_KEYS:
            value = all_env.get(key, "")
            result.append(EnvVariable.new(key, value))
        return result
