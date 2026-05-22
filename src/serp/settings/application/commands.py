"""
Settings 域 - 应用服务（用例编排）。
"""
import logging
from typing import Callable

from src.serp.shared import Result, EventBus

from ..domain.entities import Settings as SettingsAggregate, Store
from ..domain.value_objects import ModelConfig, PricingFormula, EnvVariable
from ..domain.services import SettingsValidationService, FEATURE_MODEL_KEYS, MANAGED_ENV_KEYS
from ..domain.events import (
    SettingsUpdated,
    EnvVariablesChanged,
    StoreCreated,
    StoreUpdated,
    StoreRemoved,
    SettingsImported,
)
from ..domain.repositories import SettingsRepository, StoreRepository, EnvRepository
from ..facade import SettingsFacade
from .dto import (
    SettingsViewDTO,
    SettingsExportDTO,
    ImportPreviewDTO,
    ImportResultDTO,
)

logger = logging.getLogger(__name__)


class SettingsApplicationService(SettingsFacade):
    """Settings 域应用服务 — 实现 SettingsFacade，编排领域对象和仓储。"""

    def __init__(
        self,
        settings_repo: SettingsRepository,
        store_repo: StoreRepository,
        env_repo: EnvRepository,
        event_bus: EventBus,
    ):
        self._settings_repo = settings_repo
        self._store_repo = store_repo
        self._env_repo = env_repo
        self._event_bus = event_bus

    # ==================== 查询 ====================

    def get_view(self) -> SettingsViewDTO:
        settings = self._settings_repo.load()
        stores = self._store_repo.load_all()
        env_vars = self._env_repo.read_managed()

        return SettingsViewDTO(
            models=[m.to_dict() for m in settings.models],
            feature_models=settings.feature_models,
            pricing_formulas=[f.to_dict() for f in settings.pricing_formulas],
            env={v.key: {"value": v.masked, "configured": v.configured} for v in env_vars},
            stores=[s.to_view() for s in stores],
            feature_model_keys=FEATURE_MODEL_KEYS,
        )

    def export_payload(self, include_secrets: bool = False) -> SettingsExportDTO:
        settings = self._settings_repo.load()
        stores = self._store_repo.load_all()
        all_env = self._env_repo.read_all()

        models_data = []
        for model in settings.models:
            m = model.to_dict()
            if not include_secrets:
                m["api_key_env"] = ""
            models_data.append(m)

        env_status = {}
        for key in MANAGED_ENV_KEYS:
            value = all_env.get(key, "")
            env_status[key] = {
                "value": EnvVariable._mask(value) if value and not include_secrets else value,
                "configured": bool(value),
            }

        return SettingsExportDTO(
            settings={"models": models_data, "feature_models": settings.feature_models},
            stores=[s.to_dict() for s in stores],
            env=env_status,
            meta={
                "version": settings.version,
                "exported_features": list(FEATURE_MODEL_KEYS.keys()),
            },
        )

    def get_env_status(self) -> dict:
        env_vars = self._env_repo.read_managed()
        return {v.key: {"value": v.masked, "configured": v.configured} for v in env_vars}

    def get_stores(self) -> list[dict]:
        return [s.to_view() for s in self._store_repo.load_all()]

    def get_models(self) -> list[dict]:
        settings = self._settings_repo.load()
        return [m.to_dict() for m in settings.models]

    def get_feature_model(self, feature_key: str) -> str:
        settings = self._settings_repo.load()
        return settings.feature_models.get(feature_key, "")

    def get_pricing_formulas(self, platform: str = "") -> list[dict]:
        settings = self._settings_repo.load()
        formulas = settings.pricing_formulas
        if platform:
            formulas = [f for f in formulas if f.platform == platform]
        return [f.to_dict() for f in formulas]

    # ==================== 命令 ====================

    def update(self, data: dict) -> dict:
        settings = self._settings_repo.load()
        stores = self._store_repo.load_all()
        restart_required = False

        settings_data = data.get("settings") or {}
        if settings_data:
            settings.update_from_dict(settings_data)
            self._settings_repo.save(settings)
            self._event_bus.publish(SettingsUpdated(changes=settings_data))

        stores_data = data.get("stores")
        if isinstance(stores_data, list):
            new_stores = []
            for s_data in stores_data:
                existing = next((s for s in stores if s.id == s_data.get("id")), None)
                if existing:
                    existing.update_credentials(
                        client_id=s_data.get("client_id", ""),
                        api_key=s_data.get("api_key", ""),
                        client_secret=s_data.get("client_secret", ""),
                        token=s_data.get("token", ""),
                        warehouse_id=s_data.get("warehouse_id", ""),
                    )
                    if "name" in s_data:
                        existing.name = s_data["name"]
                    if "platform" in s_data:
                        existing.platform = s_data["platform"]
                    if "enabled" in s_data:
                        existing.enabled = s_data["enabled"]
                    new_stores.append(existing)
                    self._event_bus.publish(StoreUpdated(store_id=existing.id, store_name=existing.name))
                else:
                    store = Store.from_dict(s_data)
                    new_stores.append(store)
                    self._event_bus.publish(StoreCreated(store_id=store.id, store_name=store.name))

            new_ids = {s.get("id") for s in stores_data if isinstance(s, dict)}
            for old_store in stores:
                if old_store.id not in new_ids:
                    self._event_bus.publish(StoreRemoved(store_id=old_store.id, store_name=old_store.name))

            self._store_repo.save_all(new_stores)

        env_updates = data.get("env") or {}
        safe_updates = {}
        for key, value in env_updates.items():
            if value is None:
                continue
            if EnvVariable.is_masked_placeholder(str(value)):
                continue
            safe_updates[str(key).strip()] = str(value)
        if safe_updates:
            self._env_repo.write(safe_updates)
            restart_required = True
            self._event_bus.publish(EnvVariablesChanged(changed_keys=list(safe_updates.keys())))

        return {"success": True, "restart_required": restart_required}

    def preview_import(self, payload: dict) -> ImportPreviewDTO:
        current_settings = self._settings_repo.load()
        current_stores = self._store_repo.load_all()
        all_env = self._env_repo.read_all()

        incoming = payload.get("settings", {}) if isinstance(payload, dict) else {}
        incoming_stores_raw = payload.get("stores", []) if isinstance(payload, dict) else []
        incoming_env_raw = payload.get("env", {}) if isinstance(payload, dict) else {}

        current_models = {m.id: m for m in current_settings.models}
        models_added = []
        models_updated = []
        for m_data in incoming.get("models", []) if isinstance(incoming, dict) else []:
            model_id = m_data.get("id", "")
            if model_id in current_models:
                models_updated.append(m_data)
            else:
                models_added.append(m_data)

        feature_diff = {}
        incoming_features = incoming.get("feature_models", {}) if isinstance(incoming, dict) else {}
        for key, value in incoming_features.items():
            if current_settings.feature_models.get(key) != value:
                feature_diff[key] = {"from": current_settings.feature_models.get(key), "to": value}

        current_store_ids = {s.id for s in current_stores}
        stores_added = []
        stores_updated = []
        for s_data in incoming_stores_raw if isinstance(incoming_stores_raw, list) else []:
            sid = s_data.get("id", "") if isinstance(s_data, dict) else ""
            if sid in current_store_ids:
                stores_updated.append(s_data if isinstance(s_data, dict) else {})
            else:
                stores_added.append(s_data if isinstance(s_data, dict) else {})

        env_diff = {}
        for key, info in (incoming_env_raw.items() if isinstance(incoming_env_raw, dict) else []):
            incoming_val = info.get("value", "") if isinstance(info, dict) else str(info)
            current_val = all_env.get(key, "")
            if incoming_val and incoming_val != current_val and not EnvVariable.is_masked_placeholder(incoming_val):
                env_diff[key] = {"from_configured": bool(current_val), "to_configured": bool(incoming_val)}

        summary = {
            "models": len(models_added) + len(models_updated),
            "models_added": len(models_added),
            "models_updated": len(models_updated),
            "feature_models": len(feature_diff),
            "stores": len(stores_added) + len(stores_updated),
            "stores_added": len(stores_added),
            "stores_updated": len(stores_updated),
            "env": len(env_diff),
        }

        return ImportPreviewDTO(
            models_diff={"added": models_added, "updated": models_updated},
            feature_models_diff=feature_diff,
            pricing_formulas_diff={},
            stores_diff={"added": stores_added, "updated": stores_updated},
            env_diff=env_diff,
            summary=summary,
        )

    def apply_import(self, payload: dict) -> ImportResultDTO:
        preview = self.preview_import(payload)
        errors = []

        try:
            settings = self._settings_repo.load()
            stores = self._store_repo.load_all()

            incoming = payload.get("settings", {}) if isinstance(payload, dict) else {}
            incoming_stores_raw = payload.get("stores", []) if isinstance(payload, dict) else []
            incoming_env_raw = payload.get("env", {}) if isinstance(payload, dict) else {}

            incoming_models_dict = {}
            for m_data in incoming.get("models", []) if isinstance(incoming, dict) else []:
                if isinstance(m_data, dict) and m_data.get("id"):
                    incoming_models_dict[m_data["id"]] = m_data

            merged_models = []
            for model in settings.models:
                if model.id in incoming_models_dict:
                    merged_models.append(ModelConfig.from_dict(incoming_models_dict[model.id]))
                    del incoming_models_dict[model.id]
                else:
                    merged_models.append(model)
            for m_data in incoming_models_dict.values():
                merged_models.append(ModelConfig.from_dict(m_data))

            merged_features = dict(settings.feature_models)
            if isinstance(incoming, dict):
                merged_features.update(incoming.get("feature_models", {}))

            settings._models = merged_models
            settings._feature_models = merged_features
            self._settings_repo.save(settings)

            incoming_stores_dict = {}
            for s_data in (incoming_stores_raw if isinstance(incoming_stores_raw, list) else []):
                if isinstance(s_data, dict) and s_data.get("id"):
                    incoming_stores_dict[s_data["id"]] = s_data

            merged_stores = []
            existing_ids = set()
            for store in stores:
                if store.id in incoming_stores_dict:
                    s_data = incoming_stores_dict[store.id]
                    store.update_credentials(
                        client_id=s_data.get("client_id", ""),
                        api_key=s_data.get("api_key", ""),
                        client_secret=s_data.get("client_secret", ""),
                        token=s_data.get("token", ""),
                        warehouse_id=s_data.get("warehouse_id", ""),
                    )
                    merged_stores.append(store)
                    existing_ids.add(store.id)
                else:
                    merged_stores.append(store)
                    existing_ids.add(store.id)
            for sid, s_data in incoming_stores_dict.items():
                if sid not in existing_ids:
                    merged_stores.append(Store.from_dict(s_data))

            self._store_repo.save_all(merged_stores)

            env_updates = {}
            for key, info in (incoming_env_raw.items() if isinstance(incoming_env_raw, dict) else []):
                value = info if isinstance(info, str) else info.get("value", "")
                if value and not EnvVariable.is_masked_placeholder(value):
                    env_updates[key] = value
            restart_required = bool(env_updates)
            if env_updates:
                self._env_repo.write(env_updates)

            self._event_bus.publish(SettingsImported(summary=preview.summary))

            return ImportResultDTO(success=True, summary=preview.summary, restart_required=restart_required)
        except Exception as e:
            errors.append(str(e))
            return ImportResultDTO(success=False, summary=preview.summary or {}, errors=errors)
