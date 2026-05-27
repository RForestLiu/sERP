"""
Settings 域 - 领域事件处理器。
订阅 shared event_bus 中的事件，执行副作用（日志、通知等）。
"""
import logging

from ..domain.events import (
    SettingsUpdated,
    EnvVariablesChanged,
    StoreCreated,
    StoreUpdated,
    StoreRemoved,
    SettingsImported,
)

logger = logging.getLogger(__name__)


def log_settings_updated(event: SettingsUpdated):
    logger.info("Settings updated: %s keys changed", len(event.changes))


def log_env_changed(event: EnvVariablesChanged):
    logger.info("Env variables changed: %s", event.changed_keys)


def log_store_created(event: StoreCreated):
    logger.info("Store created: %s (%s)", event.store_name, event.store_id)


def log_store_updated(event: StoreUpdated):
    logger.info("Store updated: %s (%s)", event.store_name, event.store_id)


def log_store_removed(event: StoreRemoved):
    logger.info("Store removed: %s (%s)", event.store_name, event.store_id)


def log_settings_imported(event: SettingsImported):
    logger.info("Settings imported: %s", event.summary)
