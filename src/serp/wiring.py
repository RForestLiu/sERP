"""
wiring.py — 依赖注入装配。

集中创建所有域 Facade 实例、事件总线、仓储，供给 app.py。
目前只完整实现了 Settings 域，其他域后续追加。
"""
import os
import logging

from src.serp.shared import SyncEventBus, FacadeRegistry

logger = logging.getLogger(__name__)

STORES_FILE = None  # 由 init() 设置，供旧 app.py 路由兼容


def create_settings_facade(data_root: str, env_file: str):
    """装配 Settings 域：仓储 → 事件总线 → 应用服务 → 蓝图"""
    from src.serp.settings.domain.events import (
        SettingsUpdated,
        EnvVariablesChanged,
        StoreCreated,
        StoreUpdated,
        StoreRemoved,
        SettingsImported,
    )
    from src.serp.settings.infrastructure.json_repositories import (
        JsonSettingsRepository,
        JsonStoreRepository,
        DotEnvRepository,
    )
    from src.serp.settings.infrastructure import handlers
    from src.serp.settings.application.commands import SettingsApplicationService

    event_bus = SyncEventBus()

    # 事件订阅
    event_bus.subscribe(SettingsUpdated, handlers.log_settings_updated)
    event_bus.subscribe(EnvVariablesChanged, handlers.log_env_changed)
    event_bus.subscribe(StoreCreated, handlers.log_store_created)
    event_bus.subscribe(StoreUpdated, handlers.log_store_updated)
    event_bus.subscribe(StoreRemoved, handlers.log_store_removed)
    event_bus.subscribe(SettingsImported, handlers.log_settings_imported)

    settings_repo = JsonSettingsRepository(os.path.join(data_root, "settings.json"))
    store_repo = JsonStoreRepository(os.path.join(data_root, "stores.json"))
    env_repo = DotEnvRepository(env_file)

    facade = SettingsApplicationService(settings_repo, store_repo, env_repo, event_bus)

    global STORES_FILE
    STORES_FILE = os.path.join(data_root, "stores.json")

    logger.info("Settings domain wired: event_bus=%s, repos=3", event_bus.__class__.__name__)
    return facade, event_bus


def create_registry() -> FacadeRegistry:
    return FacadeRegistry()
