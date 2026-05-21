import os
import json
import re
import shutil
import subprocess
import sys
import logging
import logging.config
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock

# ★ 加载 .env 到 os.environ，确保 ${VAR} 占位符可解析
# 注：使用 os.getcwd() 而非 __file__，因为 WSL 下 Python 解析 Linux 路径会出错
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))

# ★ 日志配置必须在此处（Flask reloader 子进程不会执行 main.py，只导入 app.py）
# ★ 强制 stdout/stderr 使用 UTF-8，否则 Windows GBK 编码会导致 emoji 日志报错丢弃
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

logging.config.dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '%(asctime)s | %(levelname)-5s | %(name)s | %(message)s',
        'datefmt': '%H:%M:%S',
    }},
    'handlers': {'console': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://sys.stdout',
        'formatter': 'default',
    }},
    'root': {'level': 'DEBUG', 'handlers': ['console']},
    'loggers': {
        'werkzeug': {'level': 'INFO', 'handlers': ['console'], 'propagate': False},
    },
    'disable_existing_loggers': False,
})

from pathlib import Path
from urllib.parse import quote

from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import cross_origin
from werkzeug.utils import secure_filename
import requests
from src.serp.wiring import create_settings_facade, create_logistics_facade, create_ozon_category_facade, create_collect_facade

app = Flask(__name__)
logger = logging.getLogger(__name__)
logger.info("=" * 50)
logger.info("sERP 启动中... | Flask %s | Debug=%s", app.name, app.debug)
logger.info("=" * 50)

# --------------- 配置 ---------------
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
SETTINGS_FILE = os.path.join(DATA_ROOT, "settings.json")
SETTINGS_FACADE, _SETTINGS_EVENT_BUS = create_settings_facade(DATA_ROOT, ENV_FILE)

os.makedirs(DATA_ROOT, exist_ok=True)

# ── DDD: Settings 域蓝图（替代旧 /api/settings/* 路由）──
from src.serp.settings.interfaces.routes import create_settings_blueprint
settings_bp = create_settings_blueprint(SETTINGS_FACADE)
app.register_blueprint(settings_bp)

# ── DDD: Logistics 域蓝图（替代旧 /api/logistics/* 路由）──
LOGISTICS_FACADE = create_logistics_facade(DATA_ROOT)
from src.serp.logistics.interfaces.routes import create_logistics_blueprint
logistics_bp = create_logistics_blueprint(LOGISTICS_FACADE)
app.register_blueprint(logistics_bp)

# ── DDD: Product 域蓝图（替代旧 /api/products/* /api/img_proxy /api/upload-video 等路由）──
from src.serp.wiring import create_product_facade
PRODUCT_FACADE = create_product_facade(DATA_ROOT, SETTINGS_FACADE, _SETTINGS_EVENT_BUS)
from src.serp.product.interfaces.routes import create_product_blueprint, create_product_static_blueprint
product_bp = create_product_blueprint(PRODUCT_FACADE, settings_facade=SETTINGS_FACADE)
product_static_bp = create_product_static_blueprint(PRODUCT_FACADE, data_root=DATA_ROOT)
app.register_blueprint(product_bp)
app.register_blueprint(product_static_bp)

# ── DDD: OzonCategory 域蓝图（替代旧 /api/ozon/<store_id>/category-tree 等路由）──
OZON_CATEGORY_FACADE = create_ozon_category_facade(DATA_ROOT, SETTINGS_FACADE, _SETTINGS_EVENT_BUS)
from src.serp.ozon_category.interfaces.routes import create_ozon_category_blueprint
ozon_category_bp = create_ozon_category_blueprint(OZON_CATEGORY_FACADE)
app.register_blueprint(ozon_category_bp)

# ── DDD: ImageTask 域蓝图（替代旧 /api/tasks/* /api/generate /api/task-types 等路由）──
from src.serp.wiring import create_imagetask_facade
IMAGETASK_FACADE = create_imagetask_facade(DATA_ROOT, SETTINGS_FACADE, _SETTINGS_EVENT_BUS)
from src.serp.imagetask.interfaces.routes import create_imagetask_blueprint
imagetask_bp = create_imagetask_blueprint(IMAGETASK_FACADE)
app.register_blueprint(imagetask_bp)

# ── DDD: Collect 域蓝图（替代旧 /api/collect/* 路由）──
COLLECT_FACADE = create_collect_facade(DATA_ROOT, SETTINGS_FACADE, _SETTINGS_EVENT_BUS)
from src.serp.collect.interfaces.routes import create_collect_blueprint
collect_bp = create_collect_blueprint(COLLECT_FACADE, data_root=DATA_ROOT)
app.register_blueprint(collect_bp)

# ── DDD: Listing 域蓝图（替代旧 /api/listings/* /api/ozon/*/listing/* /api/auto-fill/* 等路由）──
from src.serp.wiring import create_listing_facade
LISTING_FACADE = create_listing_facade(DATA_ROOT, SETTINGS_FACADE, PRODUCT_FACADE, OZON_CATEGORY_FACADE, _SETTINGS_EVENT_BUS)
from src.serp.listing.interfaces.routes import create_listing_blueprint, create_listing_page_blueprint
listing_bp = create_listing_blueprint(LISTING_FACADE)
listing_page_bp = create_listing_page_blueprint()
app.register_blueprint(listing_bp)
app.register_blueprint(listing_page_bp)

# 向后兼容：旧代码引用 STORES_FILE
STORES_FILE = os.path.join(DATA_ROOT, "stores.json")

# --------------- 路由 ---------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/task_images/<task_id>/<path:filename>")
def serve_task_image(task_id, filename):
    folder = os.path.join(DATA_ROOT, f"task_{task_id}")
    return send_from_directory(folder, filename)


@app.route("/collect_images/<task_id>/<path:filename>")
def serve_collect_image(task_id, filename):
    """服务采集任务的图片文件"""
    folder = os.path.join(DATA_ROOT, f"collect_{task_id}")
    return send_from_directory(folder, filename)

# ==================== 正式产品管理 ====================
PRODUCTS_FILE = os.path.join(DATA_ROOT, "products.json")
STORES_FILE = os.path.join(DATA_ROOT, "stores.json")
SYNC_STATE_FILE = os.path.join(DATA_ROOT, "sync_state.json")
PRODUCTS_FILE_LOCK = RLock()

# 店铺状态枚举
STORE_STATUSES = ["未上架", "待发布", "审核中", "已上架", "审核拒绝", "下架回归中"]


def _load_sync_state():
    """加载同步状态"""
    if os.path.exists(SYNC_STATE_FILE):
        try:
            with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}


def _save_sync_state(state):
    """保存同步状态"""
    try:
        with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except:
        pass

MANAGED_ENV_KEYS = [
    "API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "IMAGE_MODEL", "IMAGE_SIZE",
    "DEEPSEEK_API_KEY", "DEEPSEEK_API_URL", "DEEPSEEK_AUTO_FILL_MODEL", "DEEPSEEK_CATEGORY_MODEL", "DEEPSEEK_REVIEW_MODEL",
    "PROXY", "PROXY_ENABLED",
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


def _read_env_file():
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.rstrip("\n")
                stripped = raw.strip()
                if not stripped or stripped.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _write_env_values(updates):
    existing_lines = []
    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                existing_lines = f.read().splitlines()
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
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines).rstrip() + "\n")
    for key, value in updates.items():
        os.environ[key] = value


def _mask_secret(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return "••••" + value[-4:]


def _extract_env_name(value):
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return value[2:-1]
    return ""


def _env_status(keys):
    file_env = _read_env_file()
    result = {}
    for key in sorted(set(keys)):
        value = file_env.get(key, os.getenv(key, ""))
        result[key] = {"configured": bool(value), "masked": _mask_secret(value)}
    return result


def _load_settings():
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
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


def _save_settings(settings):
    os.makedirs(DATA_ROOT, exist_ok=True)
    payload = {
        "version": 1,
        "models": settings.get("models", []),
        "feature_models": settings.get("feature_models", {}),
        "updated_at": datetime.now().isoformat(),
    }
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return payload


def _normalize_store_config(store):
    item = dict(store or {})
    for field in ("client_id", "api_key", "token"):
        env_field = field + "_env"
        if env_field in item:
            env_name = str(item.get(env_field) or "").strip()
            item[field] = "${" + env_name + "}" if env_name else ""
            item.pop(env_field, None)
    return item


def _store_env_keys(stores):
    keys = []
    for store in stores or []:
        for field in ("client_id", "api_key", "token"):
            env_name = _extract_env_name(store.get(field))
            if env_name:
                keys.append(env_name)
    return keys


def _settings_export_payload(include_secrets=False):
    settings = _load_settings()
    stores = _load_store_configs()
    env_keys = set(MANAGED_ENV_KEYS)
    for model in settings.get("models", []):
        if model.get("api_key_env"):
            env_keys.add(model["api_key_env"])
    env_keys.update(_store_env_keys(stores))
    file_env = _read_env_file()
    env_values = {}
    for key in sorted(env_keys):
        value = file_env.get(key, os.getenv(key, ""))
        env_values[key] = value if include_secrets else (_mask_secret(value) if value else "")
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "settings": settings,
        "stores": stores,
        "env": env_values,
        "secrets_included": bool(include_secrets),
    }


def _settings_diff(import_payload):
    current = _settings_export_payload(include_secrets=False)
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
    for key, value in (incoming_settings.get("feature_models", {}) if isinstance(incoming_settings, dict) else {}).items():
        if current_features.get(key) != value:
            diff["feature_models"].append({"key": key, "from": current_features.get(key, ""), "to": value})

    current_stores = {s.get("id"): s for s in current.get("stores", [])}
    for store in incoming_stores if isinstance(incoming_stores, list) else []:
        sid = store.get("id")
        if sid:
            diff["stores"].append({"id": sid, "action": "update" if sid in current_stores else "add"})

    file_env = _read_env_file()
    for key, value in incoming_env.items() if isinstance(incoming_env, dict) else []:
        if value and not str(value).startswith("••••") and file_env.get(key, os.getenv(key, "")) != value:
            diff["env"].append({"key": key, "action": "update" if key in file_env else "add"})
    return diff


def _load_stores():
    """加载店铺列表，并解析环境变量形式的凭证占位符。"""
    if os.path.exists(STORES_FILE):
        try:
            with open(STORES_FILE, "r", encoding="utf-8") as f:
                stores = json.load(f)
            return [_resolve_store_credentials(store) for store in stores]
        except:
            pass
    return []


def _resolve_env_ref(value):
    """Resolve ${ENV_NAME} placeholders from local environment variables."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value


def _resolve_store_credentials(store):
    resolved = dict(store)
    for key in ("client_id", "api_key", "token"):
        resolved[key] = _resolve_env_ref(resolved.get(key, ""))
    return resolved


def _load_store_configs():
    """加载店铺原始配置，不解析凭证占位符，用于安全写回配置文件。"""
    if os.path.exists(STORES_FILE):
        try:
            with open(STORES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []


def _public_store(store):
    public = dict(store)
    public["credentials_configured"] = bool((store.get("client_id") and store.get("api_key")) or store.get("token"))
    public["client_id"] = ""
    public["api_key"] = ""
    public["token"] = ""
    return public

def _next_store_status(current):
    """循环切换店铺状态"""
    if current not in STORE_STATUSES:
        return STORE_STATUSES[0]
    idx = STORE_STATUSES.index(current)
    return STORE_STATUSES[(idx + 1) % len(STORE_STATUSES)]

def _load_products():
    """加载正式产品数据"""
    with PRODUCTS_FILE_LOCK:
        if os.path.exists(PRODUCTS_FILE):
            try:
                with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"已注册编号": {}, "产品列表": []}

def _save_products(products_data):
    """保存正式产品数据"""
    with PRODUCTS_FILE_LOCK:
        try:
            with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
                json.dump(products_data, f, indent=2, ensure_ascii=False)
        except:
            pass

# 品类代码映射表（4位大写字母，无歧义）
CATEGORY_CODES = {
    "钱包": "WALLET", "手机壳": "PHCA", "背包": "BACK",
    "支架": "STAND", "手表": "WATCH", "帽子": "HATS",
    "首饰": "JEWL", "鞋子": "SHOE", "服装": "GARM",
    "家居": "HOME", "电子": "ELEC", "玩具": "TOYS",
    "汽车配件": "AUTO", "办公用品": "OFFC", "美妆": "BEAU",
    "运动": "SPRT", "宠物": "PETS", "食品": "FOOD",
    "箱包": "LUGG", "家具": "FURN",
}

def _guess_category(title: str) -> str:
    """根据产品标题猜测品类，返回品类中文名"""
    title_lower = title.lower()
    keywords = {
        "钱包": ["wallet", "钱包", "卡包", "钱夹"],
        "手机壳": ["phone case", "手机壳", "手机套", "case for"],
        "背包": ["backpack", "背包", "双肩包", "书包"],
        "支架": ["stand", "支架", "holder", "支撑"],
        "手表": ["watch", "手表", "腕表", "手环"],
        "帽子": ["hat", "cap", "帽子", "棒球帽"],
        "首饰": ["jewelry", "jewellery", "首饰", "项链", "手链", "戒指", "耳环"],
        "鞋子": ["shoe", "shoes", "鞋子", "运动鞋", "靴子"],
        "服装": ["clothing", "apparel", "服装", "衣服", "t-shirt", "shirt", "dress"],
        "家居": ["home", "家居", "家装", "装饰"],
        "电子": ["electronic", "电子", "充电", "cable", "adapter"],
        "玩具": ["toy", "toys", "玩具", "玩偶"],
        "汽车配件": ["auto", "car", "汽车", "车载"],
        "办公用品": ["office", "办公", "文具"],
        "美妆": ["beauty", "cosmetic", "美妆", "化妆", "护肤"],
        "运动": ["sport", "sports", "运动", "健身"],
        "宠物": ["pet", "宠物", "猫", "狗"],
        "食品": ["food", "snack", "食品", "零食", "饮料"],
        "箱包": ["luggage", "suitcase", "行李箱", "旅行箱"],
        "家具": ["furniture", "家具", "桌子", "椅子", "沙发"],
    }
    for category, kws in keywords.items():
        for kw in kws:
            if kw in title_lower:
                return category
    return "其他"

def _generate_skc(title: str) -> str:
    """根据标题生成 SKC 编码"""
    products_data = _load_products()
    registered = products_data.get("已注册编号", {})
    
    # 猜测品类
    category_cn = _guess_category(title)
    category_code = CATEGORY_CODES.get(category_cn, "OTHR")
    
    # 查找该品类已使用的最大序号
    max_num = 0
    for skc in registered.keys():
        if skc.startswith(category_code + "-"):
            try:
                num = int(skc.split("-")[1])
                if num > max_num:
                    max_num = num
            except:
                pass
    
    new_num = max_num + 1
    skc = f"{category_code}-{new_num:04d}"
    
    # 确保唯一
    while skc in registered:
        new_num += 1
        skc = f"{category_code}-{new_num:04d}"
    
    return skc, category_cn

# 产品管理模块 API / extract_from_text 路由 已迁移到 DDD Product 域蓝图（见上方 register_blueprint）


@app.route("/api/stores", methods=["GET"])
def get_stores():
    """获取所有店铺列表"""
    return jsonify([_public_store(store) for store in _load_stores()])

# ==================== 店铺凭证管理 API ====================

@app.route("/api/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    """获取单个店铺详情（不返回 Ozon 凭证明文）"""
    stores = _load_stores()
    store = next((s for s in stores if s["id"] == store_id), None)
    if not store:
        return jsonify({"error": "店铺不存在"}), 404
    return jsonify(_public_store(store))


@app.route("/api/stores/<store_id>", methods=["PUT"])
def update_store(store_id):
    """更新店铺信息。凭证请通过 .env 配置，避免写入已跟踪 JSON。"""
    data = request.get_json()
    stores = _load_store_configs()
    store = next((s for s in stores if s["id"] == store_id), None)
    if not store:
        return jsonify({"error": "店铺不存在"}), 404
    
    # 更新允许的字段
    for key in ["label", "name"]:
        if key in data:
            store[key] = data[key]
    
    try:
        with open(STORES_FILE, "w", encoding="utf-8") as f:
            json.dump(stores, f, indent=2, ensure_ascii=False)
    except:
        pass
    
    return jsonify({"success": True, "store": store})


# ==================== 物流模板 API ====================

# Logistics 域路由由 DDD 蓝图接管（见上方 register_blueprint）
# ==================== Debug: 页面HTML捕获分析 ====================

@app.route("/api/debug/capture-html", methods=["POST"])
def debug_capture_html():
    """接收扩展发送的页面HTML，保存到 data/debug/ 供分析"""
    data = request.get_json(silent=True) or {}
    html = data.get("html", "")
    url = data.get("url", "")
    note = data.get("note", "")
    form_fields_count = len(data.get("form_fields", []))

    if not html:
        return jsonify({"error": "html 不能为空"}), 400

    debug_dir = Path("data/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_url = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")[:80] if url else "unknown"
    filename = f"page_{ts}_{safe_url}.html"
    filepath = debug_dir / filename

    # 注入元信息注释到 HTML 顶部
    meta_comment = f"<!-- debug capture: {ts} | url: {url} | note: {note} | form_fields: {form_fields_count} -->\n"
    filepath.write_text(meta_comment + html, encoding="utf-8")

    meta_path = debug_dir / f"page_{ts}_{safe_url}.json"
    meta_path.write_text(json.dumps({
        "timestamp": ts,
        "url": url,
        "note": note,
        "form_fields_count": form_fields_count,
        "html_size": len(html),
        "file": filename
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("[Debug] HTML saved: %s | size=%s | url=%s", filename, len(html), url)
    return jsonify({"ok": True, "file": filename, "size": len(html)})


# 应用实例导入：从 main.py 启动应用
# if __name__ == "__main__":
#     app.run(debug=True, port=5000)
