import copy
import json
import os
from datetime import datetime
from pathlib import Path


MANAGED_ENV_KEYS = [
    "API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "IMAGE_MODEL",
    "IMAGE_SIZE",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_AUTO_FILL_MODEL",
    "DEEPSEEK_CATEGORY_MODEL",
    "DEEPSEEK_REVIEW_MODEL",
    "PROXY",
    "PROXY_ENABLED",
]


FEATURE_MODEL_KEYS = {
    "image_generation": "图片生成",
    "product_collect_image_classify": "采集图片分类",
    "ozon_category_match": "Ozon 品类匹配",
    "dianxiaomi_auto_fill": "店小秘自动填充",
    "ozon_attribute_fill": "Ozon 属性填充",
    "translation": "翻译/本地化",
    "product_specs_extract": "产品重量尺提取",
    "product_specs_review": "产品重量尺审核",
}


DEFAULT_SETTINGS = {
    "version": 1,
    "models": [
        {
            "id": "deepseek_v4_flash",
            "name": "DeepSeek V4 Flash",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1/chat/completions",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-v4-flash",
            "enabled": True,
        },
        {
            "id": "gemini_image",
            "name": "Gemini Image",
            "provider": "gemini",
            "base_url": "https://api.laozhang.ai/v1",
            "api_key_env": "API_KEY",
            "model": "gemini-3.1-flash-image-preview",
            "enabled": True,
        },
    ],
    "feature_models": {
        "image_generation": "gemini_image",
        "product_collect_image_classify": "deepseek_v4_flash",
        "ozon_category_match": "deepseek_v4_flash",
        "dianxiaomi_auto_fill": "deepseek_v4_flash",
        "ozon_attribute_fill": "deepseek_v4_flash",
        "translation": "deepseek_v4_flash",
        "product_specs_extract": "deepseek_v4_flash",
        "product_specs_review": "deepseek_v4_flash",
    },
}


class SettingsService:
    def __init__(self, env_file, settings_file, stores_file):
        self.env_file = Path(env_file)
        self.settings_file = Path(settings_file)
        self.stores_file = Path(stores_file)

    def get_view(self):
        settings = self.load_settings()
        stores = self.load_store_configs()
        env_keys = set(MANAGED_ENV_KEYS)
        for model in settings.get("models", []):
            if model.get("api_key_env"):
                env_keys.add(model["api_key_env"])
        env_keys.update(self.store_env_keys(stores))
        return {
            "success": True,
            "settings": settings,
            "stores": stores,
            "features": FEATURE_MODEL_KEYS,
            "env": self.env_status(env_keys),
        }

    def update(self, data):
        settings = data.get("settings") or {}
        stores = data.get("stores")
        env_updates = data.get("env") or {}

        if settings:
            self.save_settings(
                {
                    "models": settings.get("models", []),
                    "feature_models": settings.get("feature_models", {}),
                }
            )

        if isinstance(stores, list):
            self.save_store_configs([self.normalize_store_config(s) for s in stores])

        safe_env_updates = {}
        for key, value in env_updates.items():
            if value is None or value == "__KEEP__" or str(value).startswith("••••"):
                continue
            safe_env_updates[str(key).strip()] = str(value)
        if safe_env_updates:
            self.write_env_values(safe_env_updates)

        return {"success": True, "restart_required": True}

    def export_payload(self, include_secrets=False):
        settings = self.load_settings()
        stores = self.load_store_configs()
        env_keys = set(MANAGED_ENV_KEYS)
        for model in settings.get("models", []):
            if model.get("api_key_env"):
                env_keys.add(model["api_key_env"])
        env_keys.update(self.store_env_keys(stores))
        file_env = self.read_env_file()
        env_values = {}
        for key in sorted(env_keys):
            value = file_env.get(key, os.getenv(key, ""))
            env_values[key] = value if include_secrets else (self.mask_secret(value) if value else "")
        return {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "settings": settings,
            "stores": stores,
            "env": env_values,
            "secrets_included": bool(include_secrets),
        }

    def preview_import(self, payload):
        return {"success": True, "preview": True, "diff": self.diff(payload)}

    def apply_import(self, payload):
        diff = self.diff(payload)
        settings = payload.get("settings")
        if isinstance(settings, dict):
            current = self.load_settings()
            incoming_models = settings.get("models", [])
            if isinstance(incoming_models, list):
                by_id = {m.get("id"): m for m in current.get("models", []) if m.get("id")}
                for model in incoming_models:
                    if model.get("id"):
                        by_id[model["id"]] = model
                current["models"] = list(by_id.values())
            incoming_features = settings.get("feature_models", {})
            if isinstance(incoming_features, dict):
                current.setdefault("feature_models", {}).update(incoming_features)
            self.save_settings(current)

        stores = payload.get("stores")
        if isinstance(stores, list):
            current_stores = self.load_store_configs()
            by_id = {s.get("id"): s for s in current_stores if s.get("id")}
            for store in stores:
                if store.get("id"):
                    by_id[store["id"]] = self.normalize_store_config(store)
            self.save_store_configs(list(by_id.values()))

        env_payload = payload.get("env", {})
        env_updates = {}
        if isinstance(env_payload, dict):
            for key, value in env_payload.items():
                if value and not str(value).startswith("••••"):
                    env_updates[str(key).strip()] = str(value)
        if env_updates:
            self.write_env_values(env_updates)
        return {"success": True, "preview": False, "diff": diff, "restart_required": True}

    def diff(self, import_payload):
        current = self.export_payload(include_secrets=False)
        incoming_settings = import_payload.get("settings", {}) if isinstance(import_payload, dict) else {}
        incoming_stores = import_payload.get("stores", []) if isinstance(import_payload, dict) else []
        incoming_env = import_payload.get("env", {}) if isinstance(import_payload, dict) else {}
        diff = {"models": [], "feature_models": [], "stores": [], "env": []}

        current_models = {m.get("id"): m for m in current["settings"].get("models", [])}
        for model in incoming_settings.get("models", []) if isinstance(incoming_settings, dict) else []:
            mid = model.get("id")
            if mid:
                diff["models"].append({"id": mid, "action": "update" if mid in current_models else "add"})

        current_features = current["settings"].get("feature_models", {})
        incoming_features = incoming_settings.get("feature_models", {}) if isinstance(incoming_settings, dict) else {}
        for key, value in incoming_features.items():
            if current_features.get(key) != value:
                diff["feature_models"].append({"key": key, "from": current_features.get(key, ""), "to": value})

        current_stores = {s.get("id"): s for s in current.get("stores", [])}
        for store in incoming_stores if isinstance(incoming_stores, list) else []:
            sid = store.get("id")
            if sid:
                diff["stores"].append({"id": sid, "action": "update" if sid in current_stores else "add"})

        file_env = self.read_env_file()
        for key, value in incoming_env.items() if isinstance(incoming_env, dict) else []:
            if value and not str(value).startswith("••••") and file_env.get(key, os.getenv(key, "")) != value:
                diff["env"].append({"key": key, "action": "update" if key in file_env else "add"})
        return diff

    def read_env_file(self):
        env = {}
        if not self.env_file.exists():
            return env
        try:
            for line in self.env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
        except Exception:
            pass
        return env

    def write_env_values(self, updates):
        existing_lines = []
        if self.env_file.exists():
            try:
                existing_lines = self.env_file.read_text(encoding="utf-8").splitlines()
            except Exception:
                existing_lines = []

        seen = set()
        new_lines = []
        for raw in existing_lines:
            if "=" not in raw or raw.lstrip().startswith("#"):
                new_lines.append(raw)
                continue
            key = raw.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                seen.add(key)
            else:
                new_lines.append(raw)

        for key, value in updates.items():
            if key not in seen:
                new_lines.append(f"{key}={value}")
        self.env_file.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
        for key, value in updates.items():
            os.environ[key] = value

    def load_settings(self):
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        if self.settings_file.exists():
            try:
                loaded = json.loads(self.settings_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key in ("version", "models", "feature_models"):
                        if key in loaded:
                            settings[key] = loaded[key]
            except Exception:
                pass
        model_ids = {m.get("id") for m in settings.get("models", []) if isinstance(m, dict)}
        for model in DEFAULT_SETTINGS["models"]:
            if model["id"] not in model_ids:
                settings.setdefault("models", []).append(dict(model))
        feature_models = settings.setdefault("feature_models", {})
        for key, value in DEFAULT_SETTINGS["feature_models"].items():
            feature_models.setdefault(key, value)
        return settings

    def save_settings(self, settings):
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "models": settings.get("models", []),
            "feature_models": settings.get("feature_models", {}),
            "updated_at": datetime.now().isoformat(),
        }
        self.settings_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    def load_store_configs(self):
        if self.stores_file.exists():
            try:
                return json.loads(self.stores_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def save_store_configs(self, stores):
        self.stores_file.parent.mkdir(parents=True, exist_ok=True)
        self.stores_file.write_text(json.dumps(stores, indent=2, ensure_ascii=False), encoding="utf-8")

    def env_status(self, keys):
        file_env = self.read_env_file()
        result = {}
        for key in sorted(set(keys)):
            value = file_env.get(key, os.getenv(key, ""))
            result[key] = {"configured": bool(value), "masked": self.mask_secret(value)}
        return result

    @staticmethod
    def mask_secret(value):
        if not value:
            return ""
        if len(value) <= 8:
            return "••••"
        return "••••" + value[-4:]

    @staticmethod
    def extract_env_name(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return value[2:-1]
        return ""

    @classmethod
    def normalize_store_config(cls, store):
        item = dict(store or {})
        for field in ("client_id", "api_key", "token"):
            env_field = field + "_env"
            if env_field in item:
                env_name = str(item.get(env_field) or "").strip()
                item[field] = "${" + env_name + "}" if env_name else ""
                item.pop(env_field, None)
        return item

    @classmethod
    def store_env_keys(cls, stores):
        keys = []
        for store in stores or []:
            for field in ("client_id", "api_key", "token"):
                env_name = cls.extract_env_name(store.get(field))
                if env_name:
                    keys.append(env_name)
        return keys
