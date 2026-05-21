import os
import json
import re
import base64
import shutil
import mimetypes
import uuid
import subprocess
import sys
import io
import struct
import ctypes
import logging
import logging.config
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock
from PIL import Image

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
from src.serp.wiring import create_settings_facade, create_logistics_facade, create_ozon_category_facade

app = Flask(__name__)
logger = logging.getLogger(__name__)
logger.info("=" * 50)
logger.info("sERP 启动中... | Flask %s | Debug=%s", app.name, app.debug)
logger.info("=" * 50)

# --------------- 配置 ---------------
API_KEY = os.getenv("API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-3.1-flash-image-preview")
API_URL = f"https://api.laozhang.ai/v1beta/models/{IMAGE_MODEL}:generateContent"
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TASKS_FILE = os.path.join(DATA_ROOT, "tasks.json")
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
SETTINGS_FILE = os.path.join(DATA_ROOT, "settings.json")
SETTINGS_FACADE, _SETTINGS_EVENT_BUS = create_settings_facade(DATA_ROOT, ENV_FILE)

os.makedirs(DATA_ROOT, exist_ok=True)
if not os.path.exists(TASKS_FILE):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

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

# 向后兼容：旧代码引用 STORES_FILE
STORES_FILE = os.path.join(DATA_ROOT, "stores.json")

# --------------- 辅助函数 ---------------
def load_tasks():
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tasks(tasks):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

def task_folder(task_id):
    return os.path.join(DATA_ROOT, f"task_{task_id}")

def ensure_task_dirs(task_id):
    base = task_folder(task_id)
    os.makedirs(base, exist_ok=True)
    os.makedirs(os.path.join(base, "source_images"), exist_ok=True)
    os.makedirs(os.path.join(base, "drafts"), exist_ok=True)
    os.makedirs(os.path.join(base, "generated"), exist_ok=True)

def get_task_data_path(task_id):
    return os.path.join(task_folder(task_id), "task_data.json")

def load_task_data(task_id):
    path = get_task_data_path(task_id)
    if not os.path.exists(path):
        return {"text1": "", "cards": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_task_data(task_id, data):
    ensure_task_dirs(task_id)
    path = get_task_data_path(task_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --------------- 路由 ---------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/task_images/<task_id>/<path:filename>")
def serve_task_image(task_id, filename):
    folder = task_folder(task_id)
    return send_from_directory(folder, filename)


@app.route("/collect_images/<task_id>/<path:filename>")
def serve_collect_image(task_id, filename):
    """服务采集任务的图片文件"""
    folder = os.path.join(DATA_ROOT, f"collect_{task_id}")
    return send_from_directory(folder, filename)


# --------------- API ---------------
@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_tasks()
    return jsonify(tasks)

# ── 任务类型定义 ───────────────────────────────────────────────
TASK_TYPES = [
    {"id": "batch_translate", "name": "批量翻译图片", "icon": "🌐", "description": "AI图片翻译，中→俄等", "available": True},
    {"id": "batch_crop_resize", "name": "批量裁剪/缩放", "icon": "✂️", "description": "按平台尺寸要求处理", "available": False},
    {"id": "generate_main_image", "name": "生成产品首图", "icon": "🎨", "description": "白模图+产品信息→首图", "available": False},
    {"id": "batch_replace_product", "name": "批量替换产品图", "icon": "🔄", "description": "用新产品图替换模板", "available": True},
]

@app.route("/api/task-types", methods=["GET"])
def get_task_types():
    return jsonify(TASK_TYPES)

@app.route("/api/tasks", methods=["POST"])
def create_task():
    tasks = load_tasks()
    payload = request.get_json(silent=True) or {}
    task_type = payload.get("type", "")
    # 任务名称：指定类型用类型名，否则自动递增
    if task_type:
        type_info = next((tt for tt in TASK_TYPES if tt["id"] == task_type), None)
        base_name = type_info["name"] if type_info else task_type
    else:
        base_name = "任务"
    existing_names = [t["name"] for t in tasks]
    n = 1
    while f"{base_name} {n}" in existing_names:
        n += 1
    name = f"{base_name} {n}"
    task_id = str(uuid.uuid4())[:8]
    tasks.append({
        "id": task_id,
        "name": name,
        "type": task_type,
        "created_at": datetime.now().isoformat()
    })
    save_tasks(tasks)
    save_task_data(task_id, {"text1": "", "cards": [], "skc": payload.get("skc", "")})
    return jsonify({"id": task_id, "name": name, "type": task_type})

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """删除任务及其所有数据"""
    tasks = load_tasks()
    task_info = next((t for t in tasks if t["id"] == task_id), None)
    if not task_info:
        return jsonify({"error": "任务不存在"}), 404

    tasks = [t for t in tasks if t["id"] != task_id]
    save_tasks(tasks)

    # 删除任务数据文件和目录
    task_dir = task_folder(task_id)
    task_data_file = os.path.join(task_dir, "task_data.json")
    if os.path.exists(task_data_file):
        os.remove(task_data_file)
    if os.path.exists(task_dir):
        try:
            shutil.rmtree(task_dir)
        except Exception:
            pass

    return jsonify({"deleted": task_id})

@app.route("/api/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    data = load_task_data(task_id)
    tasks = load_tasks()
    task_info = next((t for t in tasks if t["id"] == task_id), None)
    return jsonify({
        "id": task_id,
        "name": task_info["name"] if task_info else "",
        "type": task_info["type"] if task_info else "",
        "data": data
    })

@app.route("/api/tasks/<task_id>", methods=["PUT"])
def update_task(task_id):
    payload = request.get_json()
    name = payload.get("name")
    task_data = payload.get("data")
    if name is not None:
        tasks = load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["name"] = name
                break
        save_tasks(tasks)
    if task_data is not None:
        save_task_data(task_id, task_data)
    return jsonify({"status": "ok"})

@app.route("/api/tasks/<task_id>/upload_source_images", methods=["POST"])
def upload_source_images(task_id):
    ensure_task_dirs(task_id)
    files = request.files.getlist("images")
    saved = []
    for f in files:
        if f.filename == "":
            continue
        safe_name = f.filename
        save_path = os.path.join(task_folder(task_id), "source_images", safe_name)
        f.save(save_path)
        saved.append({
            "original_name": f.filename,
            "saved_name": safe_name,
            "relative_path": f"source_images/{safe_name}"
        })
    return jsonify({"saved": saved})


@app.route("/api/tasks/<task_id>/upload_ref_image/<int:ref_index>", methods=["POST"])
def upload_ref_image(task_id, ref_index):
    """上传任务的公共参考图 (ref_index: 1 或 2)"""
    if ref_index not in (1, 2):
        return jsonify({"error": "ref_index 必须为 1 或 2"}), 400
    ensure_task_dirs(task_id)
    f = request.files.get("image")
    if not f or f.filename == "":
        return jsonify({"error": "未选择图片"}), 400

    source_dir = os.path.join(task_folder(task_id), "source_images")
    data = load_task_data(task_id)
    field = f"ref_image_{ref_index}"
    old_path = data.get(field, "")

    # 删除旧参考图和历史固定名，避免同 URL 被浏览器缓存成第一次上传的图。
    old_candidates = []
    if old_path:
        old_candidates.append(os.path.join(task_folder(task_id), old_path))
    old_candidates.extend(
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.startswith(f"_ref_{ref_index}.") or name.startswith(f"_ref_{ref_index}_")
    )
    for old_file in old_candidates:
        try:
            old_abs = os.path.abspath(old_file)
            source_abs = os.path.abspath(source_dir)
            if os.path.commonpath([old_abs, source_abs]) == source_abs and os.path.isfile(old_abs):
                os.remove(old_abs)
        except Exception as e:
            logger.warning("[上传参考图] 删除旧参考图失败: %s", e)

    ext = os.path.splitext(f.filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        ext = ".jpg"
    safe_name = f"_ref_{ref_index}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    save_path = os.path.join(source_dir, safe_name)
    f.save(save_path)

    # 更新 task_data.json
    data[field] = f"source_images/{safe_name}"
    save_task_data(task_id, data)

    logger.info("[上传参考图] task=%s ref=%s → %s", task_id, ref_index, safe_name)
    return jsonify({"success": True, "ref_index": ref_index, "field": field, "path": f"source_images/{safe_name}"})


@app.route("/api/tasks/<task_id>/import_images", methods=["POST"])
def import_images_to_task(task_id):
    """将产品图片复制到任务 source_images 目录 — 从图片管理弹窗拖拽导入"""
    data = request.get_json()
    skc = data.get("skc", "")
    entries = data.get("entries", [])

    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    product = None
    for p in product_list:
        if p["skc"] == skc:
            product = p
            break
    if not product:
        return jsonify({"error": "产品不存在"}), 404

    images_dir = product.get("images_dir", "")
    if not images_dir or not os.path.exists(images_dir):
        return jsonify({"error": "产品图片目录不存在"}), 404

    source_dir = os.path.join(task_folder(task_id), "source_images")
    os.makedirs(source_dir, exist_ok=True)

    saved = []
    for entry in entries:
        filename = entry.get("filename", "")
        if not filename:
            continue
        src_path = os.path.join(images_dir, filename)
        if not os.path.exists(src_path):
            continue
        safe_name = os.path.basename(filename)
        dest_name = safe_name
        dest_path = os.path.join(source_dir, dest_name)
        name_parts = os.path.splitext(safe_name)
        counter = 1
        while os.path.exists(dest_path):
            dest_name = f"{name_parts[0]}_{counter}{name_parts[1]}"
            dest_path = os.path.join(source_dir, dest_name)
            counter += 1
        shutil.copy2(src_path, dest_path)
        saved.append({
            "original_name": safe_name,
            "relative_path": f"source_images/{dest_name}"
        })

    return jsonify({"saved": saved})


# ── 图片压缩函数 ───────────────────────────────────────────────
def compress_image(image_data, max_size=1.5*1024*1024):
    """
    将图片压缩到 max_size 字节以下（默认 1.5MB）
    - 自动将 PNG/WebP 转为 JPEG 以获得更好压缩率
    - 自适应质量：从 85 开始递减，最低至 30
    - 若质量降到最低仍超标，则降低分辨率
    返回: (压缩后的字节数据, mime类型)
    """
    try:
        img = Image.open(io.BytesIO(image_data))
        
        # RGBA/LA/P 转 RGB（JPEG 不支持 Alpha）
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # 自适应质量压缩
        quality = 85
        while quality >= 30:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            if buf.tell() <= max_size:
                return buf.getvalue(), 'image/jpeg'
            quality -= 5
        
        # 最低质量仍超标，降低分辨率
        scale = 0.9
        while True:
            w, h = int(img.width * scale), int(img.height * scale)
            if w < 100 or h < 100:
                break
            resized = img.resize((w, h), Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format='JPEG', quality=30, optimize=True)
            if buf.tell() <= max_size:
                return buf.getvalue(), 'image/jpeg'
            scale *= 0.9
        
        # 兜底：返回原数据
        return image_data, 'image/jpeg'
    except Exception as e:
        # 压缩失败则返回原数据
        return image_data, 'image/jpeg'


@app.route("/api/generate", methods=["POST"])
def generate_image():
    data = request.get_json()
    task_id = data.get("task_id")
    card_id = data.get("card_id")
    prompt = data.get("prompt", "")
    source_image_path = data.get("source_image_path", "")
    extra_image_paths = data.get("extra_image_paths") or []
    auto_compress = data.get("auto_compress", True)

    if not API_KEY:
        return jsonify({"error": "API_KEY not configured"}), 500

    ref_image_data = None
    mime_type = "image/jpeg"
    if source_image_path:
        full_path = os.path.join(task_folder(task_id), source_image_path)
        if os.path.exists(full_path):
            mime_type = mimetypes.guess_type(full_path)[0] or "image/jpeg"
            with open(full_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            ref_image_data = {"mime_type": mime_type, "data": encoded}

    parts = [{"text": prompt}]
    if ref_image_data:
        parts.append({"inline_data": ref_image_data})

    # 批量替换产品：附加参考图（图2、图3）
    for img_path in extra_image_paths:
        full = os.path.join(task_folder(task_id), img_path)
        if os.path.exists(full):
            img_mime = mimetypes.guess_type(full)[0] or "image/jpeg"
            with open(full, "rb") as f:
                img_enc = base64.b64encode(f.read()).decode("utf-8")
            parts.append({"inline_data": {"mime_type": img_mime, "data": img_enc}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"imageSize": "2K"}
        }
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=180)
        if resp.status_code != 200:
            return jsonify({"error": f"API Error {resp.status_code}: {resp.text}"}), 500

        result = resp.json()
        image_part = None
        for candidate in result.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data and inline_data.get("data"):
                    image_part = inline_data
                    break
            if image_part:
                break

        if not image_part:
            return jsonify({"error": "No image data in response", "detail": result}), 500

        mime = image_part.get("mimeType") or image_part.get("mime_type") or "image/png"
        ext = "jpg" if mime == "image/jpeg" else "webp" if mime == "image/webp" else "png"
        file_name = f"{card_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{ext}"

        draft_dir = os.path.join(task_folder(task_id), "drafts")
        os.makedirs(draft_dir, exist_ok=True)
        draft_path = os.path.join(draft_dir, file_name)
        image_data = base64.b64decode(image_part["data"])

        # 自动压缩
        if auto_compress:
            compressed_data, compressed_mime = compress_image(image_data)
            if len(compressed_data) < len(image_data):
                image_data = compressed_data
                # 压缩后统一为 jpg
                file_name = f"{card_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
                draft_path = os.path.join(draft_dir, file_name)

        with open(draft_path, "wb") as f:
            f.write(image_data)

        url = f"/task_images/{task_id}/drafts/{file_name}"
        base64_img = base64.b64encode(image_data).decode("utf-8")
        return jsonify({
            "success": True,
            "url": url,
            "base64": f"data:{mime};base64,{base64_img}",
            "draft_file": f"drafts/{file_name}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tasks/<task_id>/save_images", methods=["POST"])
def save_images(task_id):
    draft_dir = os.path.join(task_folder(task_id), "drafts")
    gen_dir = os.path.join(task_folder(task_id), "generated")
    os.makedirs(gen_dir, exist_ok=True)

    moved = []
    if os.path.exists(draft_dir):
        for fname in os.listdir(draft_dir):
            src = os.path.join(draft_dir, fname)
            dst = os.path.join(gen_dir, fname)
            shutil.move(src, dst)
            moved.append(fname)
    task_data = load_task_data(task_id)
    for card in task_data.get("cards", []):
        draft = card.get("generated_draft")
        if draft:
            fname = os.path.basename(draft)
            if fname in moved:
                card["generated_final"] = f"generated/{fname}"
                card["generated_draft"] = ""
    save_task_data(task_id, task_data)
    return jsonify({"moved": moved, "generated_dir": f"task_images/{task_id}/generated"})

@app.route("/api/tasks/<task_id>/save_to_product", methods=["POST"])
def save_to_product(task_id):
    """将任务的生成图片复制到指定产品的图片集/子集"""
    data = request.get_json()
    skc = data.get("skc")
    setName = data.get("setName")
    subName = data.get("subName", "")

    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    product = next((p for p in product_list if p["skc"] == skc), None)
    if not product:
        return jsonify({"error": "产品不存在"}), 404

    images_dir = product.get("images_dir", "")
    if not images_dir or not os.path.exists(images_dir):
        return jsonify({"error": "产品图片目录不存在"}), 404

    gen_dir = os.path.join(task_folder(task_id), "generated")
    gen_files = []
    if os.path.exists(gen_dir):
        gen_files = sorted([f for f in os.listdir(gen_dir) if os.path.isfile(os.path.join(gen_dir, f))])

    # Fallback to draft files (not yet "saved to task folder")
    if not gen_files:
        drafts_dir = os.path.join(task_folder(task_id), "drafts")
        if os.path.exists(drafts_dir):
            task_data = load_task_data(task_id)
            seen = set()
            for card in task_data.get("cards", []):
                draft = card.get("generated_draft", "")
                if draft:
                    fname = os.path.basename(draft)
                    fpath = os.path.join(task_folder(task_id), draft)
                    if fname not in seen and os.path.isfile(fpath):
                        seen.add(fname)
                        gen_files.append(fname)
            gen_dir = drafts_dir

    if not gen_files:
        return jsonify({"saved": [], "message": "没有生成图片可保存"}), 200

    path_prefix = f"{setName}/{subName}/" if subName else f"{setName}/"
    target_dir = os.path.join(images_dir, path_prefix)
    os.makedirs(target_dir, exist_ok=True)

    saved = []
    for fname in gen_files:
        src = os.path.join(gen_dir, fname)
        dest_name = fname
        dest_path = os.path.join(target_dir, dest_name)
        name_parts = os.path.splitext(fname)
        counter = 1
        while os.path.exists(dest_path):
            dest_name = f"{name_parts[0]}_{counter}{name_parts[1]}"
            dest_path = os.path.join(target_dir, dest_name)
            counter += 1
        shutil.copy2(src, dest_path)
        rel_path = (path_prefix + dest_name).replace("\\", "/")
        saved.append({"filename": rel_path, "index": 0})

    # Update image_sets
    image_sets = product.get("image_sets", {})
    if setName not in image_sets:
        image_sets[setName] = []
    max_idx = max([e.get("index", 0) for e in image_sets[setName]], default=-1)
    for entry in saved:
        max_idx += 1
        entry["index"] = max_idx
        image_sets[setName].append(entry)

    # Update image_subsets if subName
    if subName:
        image_subsets = product.get("image_subsets", {})
        image_subsets.setdefault(setName, {}).setdefault(subName, [])
        max_sub_idx = max([e.get("index", 0) for e in image_subsets[setName][subName]], default=-1)
        for entry in saved:
            sub_entry = {"filename": entry["filename"], "index": 0}
            max_sub_idx += 1
            sub_entry["index"] = max_sub_idx
            image_subsets[setName][subName].append(sub_entry)
        product["image_subsets"] = image_subsets

    product["image_sets"] = image_sets
    _save_products(products_data)

    return jsonify({"saved": saved, "count": len(saved),
                    "target": f"{skc}/{path_prefix}"})

# ── 系统剪贴板辅助 ─────────────────────────────────────────────
def _copy_files_to_clipboard(file_paths):
    """将文件路径列表写入 Windows 系统剪贴板 CF_HDROP"""
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    file_list = b""
    for p in file_paths:
        file_list += p.encode("utf-16-le") + b"\x00\x00"
    file_list += b"\x00\x00"

    dropfiles = struct.pack("Iiiii", 20, 0, 0, 0, 1)
    data = dropfiles + file_list

    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040
    hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(data))
    if not hglobal:
        raise OSError("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(hglobal)
    if not ptr:
        kernel32.GlobalFree(hglobal)
        raise OSError("GlobalLock failed")
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(hglobal)

    import win32clipboard
    win32clipboard.OpenClipboard(None)
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, hglobal)
    win32clipboard.CloseClipboard()


@app.route("/api/tasks/<task_id>/copy_to_clipboard", methods=["POST"])
def copy_task_images_to_clipboard(task_id):
    """将任务图片写入系统剪贴板（CF_HDROP 文件列表）"""
    data = request.get_json()
    img_type = data.get("type", "source")

    task_data = load_task_data(task_id)
    cards = task_data.get("cards", [])

    paths = []
    for c in cards:
        p = None
        if img_type == "source":
            p = c.get("source_image")
        else:
            p = c.get("generated_final") or c.get("generated_draft")
        if p:
            full = os.path.join(task_folder(task_id), p).replace("/", "\\")
            if os.path.exists(full):
                paths.append(full)

    if not paths:
        return jsonify({"error": "没有可复制的图片"}), 400

    try:
        _copy_files_to_clipboard(paths)
        return jsonify({"copied": len(paths)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tasks/<task_id>/compress_images", methods=["POST"])
def compress_task_images(task_id):
    """批量压缩任务 generated 目录中所有大于 1.5MB 的图片"""
    compressed_count = 0
    error_count = 0
    total_size_before = 0
    total_size_after = 0

    gen_dir = os.path.join(task_folder(task_id), "generated")
    if not os.path.exists(gen_dir):
        return jsonify({
            "success": True,
            "compressed_count": 0,
            "error_count": 0,
            "total_size_before": 0,
            "total_size_after": 0,
            "saved_bytes": 0
        })

    for fname in os.listdir(gen_dir):
        fpath = os.path.join(gen_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'):
            continue
        try:
            with open(fpath, "rb") as f:
                original_data = f.read()
            size_before = len(original_data)
            if size_before <= 1.5 * 1024 * 1024:
                continue  # 已经小于 1.5MB，跳过
            compressed_data, new_mime = compress_image(original_data)
            size_after = len(compressed_data)
            if size_after < size_before:
                # 保存压缩后的图片（统一转为 jpg）
                new_fname = os.path.splitext(fname)[0] + ".jpg"
                new_fpath = os.path.join(gen_dir, new_fname)
                with open(new_fpath, "wb") as f:
                    f.write(compressed_data)
                # 如果文件名变了，删除旧文件
                if new_fname != fname:
                    os.remove(fpath)
                total_size_before += size_before
                total_size_after += size_after
                compressed_count += 1
        except Exception as e:
            error_count += 1
            continue

    return jsonify({
        "success": True,
        "compressed_count": compressed_count,
        "error_count": error_count,
        "total_size_before": total_size_before,
        "total_size_after": total_size_after,
        "saved_bytes": total_size_before - total_size_after
    })

@app.route("/api/tasks/<task_id>/open_folder", methods=["POST"])
def open_folder(task_id):
    folder = os.path.join(task_folder(task_id), "generated")
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    if os.name == 'nt':
        os.startfile(folder)
    else:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
    return jsonify({"status": "opened", "folder": folder})

# ==================== 采集产品模块 API ====================

import threading
import uuid as uuid_lib
import asyncio

# 采集任务状态存储
collect_tasks = {}  # task_id -> {status, progress, message, result}
COLLECT_TASKS_FILE = os.path.join(DATA_ROOT, "collect_tasks.json")

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

def _load_collect_tasks():
    """从持久化文件加载采集任务"""
    if os.path.exists(COLLECT_TASKS_FILE):
        try:
            with open(COLLECT_TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def _save_collect_tasks():
    """保存采集任务到持久化文件"""
    # 只保存已完成/出错的任务摘要（不保存进行中的临时状态）
    saved = {}
    for tid, task in collect_tasks.items():
        if task["status"] in ("completed", "error"):
            saved[tid] = {
                "status": task["status"],
                "progress": task["progress"],
                "message": task["message"],
                "result": task["result"]
            }
    try:
        with open(COLLECT_TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=2, ensure_ascii=False)
    except:
        pass

# 启动时加载持久化的采集任务
_persisted_tasks = _load_collect_tasks()
for tid, tdata in _persisted_tasks.items():
    collect_tasks[tid] = tdata

def _collect_status_callback(task_id, status, progress, message):
    """采集任务状态回调"""
    if task_id in collect_tasks:
        collect_tasks[task_id]["status"] = status
        collect_tasks[task_id]["progress"] = progress
        collect_tasks[task_id]["message"] = message


def _run_collect_in_thread(url, task_id):
    """在后台线程中执行采集"""
    from collector import run_collect_pipeline
    
    collect_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "message": "等待开始...",
        "result": None,
        "created_at": datetime.now().isoformat()
    }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            run_collect_pipeline(url, task_id, _collect_status_callback)
        )
        loop.close()
        
        collect_tasks[task_id]["result"] = result
        # 任务完成后持久化
        _save_collect_tasks()
    except Exception as e:
        collect_tasks[task_id]["status"] = "error"
        collect_tasks[task_id]["message"] = f"采集异常: {str(e)}"
        collect_tasks[task_id]["result"] = {
            "task_id": task_id,
            "status": "error",
            "url": url,
            "error": str(e)
        }


@app.route("/api/collect/tasks", methods=["GET"])
def get_collect_tasks():
    """获取所有已保存的采集任务列表"""
    tasks = []
    for tid, task in collect_tasks.items():
        if task["status"] in ("completed", "error"):
            result = task.get("result") or {}
            tasks.append({
                "task_id": tid,
                "status": task["status"],
                "message": task["message"],
                "url": result.get("url", ""),
                "title": result.get("title", ""),
                "platform": result.get("platform", ""),
                "downloaded": result.get("downloaded", 0),
                "image_count": result.get("image_count", 0),
                "failed": result.get("failed", 0),
                "created_at": task.get("created_at", "")
            })
    return jsonify(tasks)


@app.route("/api/collect", methods=["POST"])
def start_collect():
    """启动采集任务"""
    data = request.get_json()
    url = data.get("url", "").strip()
    
    if not url:
        return jsonify({"error": "请输入采集网址"}), 400
    
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "请输入有效的网址（以 http:// 或 https:// 开头）"}), 400
    
    task_id = "collect_" + uuid_lib.uuid4().hex[:8]
    
    # 启动后台线程
    thread = threading.Thread(target=_run_collect_in_thread, args=(url, task_id), daemon=True)
    thread.start()
    
    return jsonify({
        "task_id": task_id,
        "status": "pending",
        "message": "任务已创建，正在启动..."
    })


@app.route("/api/collect/amazon_capture", methods=["POST"])
@cross_origin()
def amazon_capture():
    """接收 Chrome 扩展从 Amazon 页面提取的产品数据"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "no title"}), 400

    task_id = "amz_" + uuid_lib.uuid4().hex[:8]
    images = data.get("images", [])
    price = data.get("price", "")
    product_url = data.get("url", "")

    # 创建采集目录
    data_dir = os.path.join(DATA_ROOT, f"collect_{task_id}")
    images_dir = os.path.join(data_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # 保存产品数据（不含图片URL，图片已下载到本地）
    sanitized = _sanitize_product_payload(data)
    product_data_file = os.path.join(data_dir, "product_data.json")
    with open(product_data_file, "w", encoding="utf-8") as f:
        json.dump(sanitized, f, indent=2, ensure_ascii=False)

    collect_tasks[task_id] = {
        "status": "completed",
        "progress": 100,
        "message": f"Amazon 采集 — {title[:40]}",
        "created_at": datetime.now().isoformat(),
        "result": {
            "task_id": task_id,
            "status": "completed",
            "url": product_url,
            "platform": "amazon",
            "title": title,
            "price": price,
            "image_count": len(images),
            "downloaded": 0,
            "failed": 0,
            "data_dir": data_dir,
            "product_data": product_data_file.replace("\\", "/"),
            "images_mapping": None,
            "images_dir": images_dir,
            "source": "amazon_extension",
        },
    }
    _save_collect_tasks()

    # 后台下载图片
    if images:
        thread = threading.Thread(
            target=_download_amazon_images,
            args=(task_id, images, images_dir),
            daemon=True,
        )
        thread.start()

    logger.info(f"[amazon_capture] {title} (图片={len(images)})")
    return jsonify({
        "status": "ok",
        "task_id": task_id,
        "title": title,
        "image_count": len(images),
    }), 200


def _download_amazon_images(task_id, image_urls, images_dir):
    """后台下载 Amazon 图片并更新 mapping"""
    import requests as req_lib

    downloaded = 0
    failed = 0
    images_mapping = []
    session = req_lib.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.amazon.com/",
    })

    for idx, img_url in enumerate(image_urls):
        try:
            resp = session.get(img_url, timeout=30)
            if resp.status_code == 200:
                ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                    ext = ".jpg"
                filename = f"{idx+1:02d}{ext}"
                filepath = os.path.join(images_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                images_mapping.append({"index": idx, "url": img_url, "file": filename})
                downloaded += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    # 更新结果
    if task_id in collect_tasks:
        collect_tasks[task_id]["result"]["downloaded"] = downloaded
        collect_tasks[task_id]["result"]["failed"] = failed
        collect_tasks[task_id]["message"] += f" ({downloaded}图已下载)"

    # 保存 mapping
    if images_mapping:
        mapping_file = os.path.join(os.path.dirname(images_dir), "images_mapping.json")
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(images_mapping, f, indent=2, ensure_ascii=False)
        if task_id in collect_tasks:
            collect_tasks[task_id]["result"]["images_mapping"] = mapping_file.replace("\\", "/")

    _save_collect_tasks()
    logger.info(f"[amazon_capture] {task_id}: {downloaded} downloaded, {failed} failed")


# ==================== 通用浏览器采集端点 ====================

PLATFORM_PREFIX = {
    "amazon": "amz",
    "1688": "1688",
    "wildberries": "wb",
    "ozon": "ozn",
}

PLATFORM_REFERER = {
    "amazon": "https://www.amazon.com/",
    "1688": "https://detail.1688.com/",
    "wildberries": "https://www.wildberries.ru/",
    "ozon": "https://www.ozon.ru/",
}


def _compact_variant_entry(variant):
    """保留变体业务信息，移除图片 URL 等采集噪声。"""
    if not isinstance(variant, dict):
        return {}
    keep_keys = (
        "variantName",
        "price",
        "variantInfo",
        "currentVariant",
        "product_details",
        "product_description",
        "_error",
    )
    compact = {k: variant.get(k) for k in keep_keys if variant.get(k) not in (None, "", [], {})}
    images = variant.get("images", [])
    if isinstance(images, list) and images:
        compact["image_count"] = len(images)
    return compact


def _sanitize_product_payload(data):
    """产品数据只保留可填表/可展示的信息，图片 URL 交给 images_mapping 管理。"""
    sanitized = dict(data)
    sanitized["images"] = []
    if sanitized.get("variantData"):
        sanitized["variantData"] = [
            _compact_variant_entry(v) for v in sanitized["variantData"] if isinstance(v, dict)
        ]
    return sanitized


@app.route("/api/collect/browser_capture", methods=["POST"])
@cross_origin()
def browser_capture():
    """接收 Chrome 扩展从多平台提取的产品数据（支持批量变体）"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "no title"}), 400

    platform = data.get("platform", "unknown")
    prefix = PLATFORM_PREFIX.get(platform, "unk")
    task_id = prefix + "_" + uuid_lib.uuid4().hex[:8]

    images = data.get("images", [])
    price = data.get("price", "")
    product_url = data.get("url", "")
    variant_data = data.get("variantData")  # 批量变体采集时传入
    variant_count = len(variant_data) if variant_data else 0

    data_dir = os.path.join(DATA_ROOT, f"collect_{task_id}")
    images_dir = os.path.join(data_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    product_data_file = os.path.join(data_dir, "product_data.json")
    # 保存时移除图片URL（图片已下载到本地，无需在数据中保留冗长的URL）
    sanitized = _sanitize_product_payload(data)
    with open(product_data_file, "w", encoding="utf-8") as f:
        json.dump(sanitized, f, indent=2, ensure_ascii=False)

    # 计算总图片数（基于原始 data）
    total_image_count = len(images)
    if variant_data:
        for v in variant_data:
            total_image_count += len(v.get("images", []))

    collect_tasks[task_id] = {
        "status": "completed",
        "progress": 100,
        "message": f"{platform} 采集 — {title[:40]}" + (f" ({variant_count}变体)" if variant_count else ""),
        "created_at": datetime.now().isoformat(),
        "result": {
            "task_id": task_id,
            "status": "completed",
            "url": product_url,
            "platform": platform,
            "title": title,
            "price": price,
            "image_count": len(images),
            "variant_count": variant_count,
            "total_image_count": total_image_count,
            "downloaded": 0,
            "failed": 0,
            "data_dir": data_dir,
            "product_data": product_data_file.replace("\\", "/"),
            "images_mapping": None,
            "images_dir": images_dir,
            "source": "browser_extension",
            "variants": [_compact_variant_entry(v) for v in variant_data] if variant_data else [],
        },
    }
    _save_collect_tasks()

    # 所有产品统一变体结构：单规格 → 01_default，多规格 → 01_Color/02_Color...
    if not variant_data:
        variant_data = [{"variantName": "default", "price": price, "images": images, "url": product_url}]
        images = []  # 图片归入变体子目录，根 images/ 不再放文件

    if variant_data:
        thread = threading.Thread(
            target=_download_variant_images,
            args=(task_id, variant_data, images_dir, platform),
            daemon=True,
        )
        thread.start()

    logger.info(f"[browser_capture] [{platform}] {title} (变体={variant_count}, 图片={total_image_count})")
    return jsonify({
        "status": "ok",
        "task_id": task_id,
        "title": title,
        "platform": platform,
        "variant_count": variant_count,
        "image_count": total_image_count,
    }), 200


@app.route("/api/collect/send_html", methods=["POST", "OPTIONS"])
@cross_origin()
def collect_send_html():
    """接收扩展发送的页面 HTML（用于新平台采集分析）"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    html_content = data.get("html", "")
    if not html_content:
        return jsonify({"error": "no html"}), 400

    url = data.get("url", "")
    platform = data.get("platform", "unknown")
    title = data.get("title", "")

    debug_dir = os.path.join(DATA_ROOT, "debug")
    os.makedirs(debug_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9_\-一-鿿]", "_", title or "page")[:60]
    filename = f"{platform}_{safe_name}_{ts}.html"
    filepath = os.path.join(debug_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info(f"[send_html] {platform}: {title or url} -> {filename} ({len(html_content)} bytes)")
    return jsonify({
        "status": "ok",
        "filename": filename,
        "size": len(html_content),
    }), 200


def _download_variant_images(task_id, variant_data, images_dir, platform):
    """下载各变体图片到子目录: images/01_Name/, images/02_Name/..."""
    import requests as req_lib

    referer = PLATFORM_REFERER.get(platform, "https://www.amazon.com/")
    session = req_lib.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": referer,
    })

    def _download_one(url, idx, dest_dir):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                    ext = ".jpg"
                fname = f"{idx+1:02d}{ext}"
                fpath = os.path.join(dest_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(resp.content)
                return True, fname
        except Exception:
            pass
        return False, None

    total_downloaded = 0
    total_failed = 0
    all_mappings = {}

    # 各变体图片 → images/{idx+1:02d}_{variantName}/
    for vi, variant in enumerate(variant_data):
        vname = variant.get("variantName", f"variant_{vi}")
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", vname)[:50]
        vdir = os.path.join(images_dir, f"{vi+1:02d}_{safe_name}")
        os.makedirs(vdir, exist_ok=True)

        vimgs = variant.get("images", [])
        mappings = []
        for i2, url in enumerate(vimgs):
            ok, fname = _download_one(url, i2, vdir)
            if ok:
                mappings.append({"index": i2, "url": url, "file": fname, "subdir": os.path.basename(vdir)})
                total_downloaded += 1
            else:
                total_failed += 1
        if mappings:
            all_mappings[variant.get("variantName", f"variant_{vi}")] = mappings

    # 更新结果
    if task_id in collect_tasks:
        collect_tasks[task_id]["result"]["downloaded"] = total_downloaded
        collect_tasks[task_id]["result"]["failed"] = total_failed
        collect_tasks[task_id]["message"] += f" ({total_downloaded}图已下载)"

    if all_mappings:
        mapping_file = os.path.join(os.path.dirname(images_dir), "images_mapping.json")
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(all_mappings, f, indent=2, ensure_ascii=False)
        if task_id in collect_tasks:
            collect_tasks[task_id]["result"]["images_mapping"] = mapping_file.replace("\\", "/")

    _save_collect_tasks()
    logger.info(f"[browser_capture] {task_id} [{platform}]: {total_downloaded} downloaded, {total_failed} failed ({len(variant_data)} variants)")


@app.route("/api/collect/dxm_capture", methods=["POST"])
def dxm_capture():
    """接收 Chrome 扩展截获的店小秘采集 API 数据"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    url = data.get("url", "")
    page_url = data.get("pageUrl", "")

    # 提取响应体 (page injection 方式) 或请求体 (webRequest 方式)
    resp_body = data.get("responseBody") or data.get("responseText") or {}
    if isinstance(resp_body, str):
        try:
            resp_body = json.loads(resp_body)
        except (json.JSONDecodeError, ValueError):
            resp_body = {}

    req_body = data.get("requestBody") or {}

    # 保存调试日志
    _log_dxm_capture(data, resp_body or req_body)

    # 先尝试从响应体中提取产品数据
    product_data = _extract_dxm_product(resp_body, url, page_url)

    if product_data:
        # 有完整产品数据 → 直接创建任务
        _create_dxm_task(product_data)
        return jsonify({"status": "ok", "task_id": "dxm_created", "title": product_data.get("title")}), 200

    # 没有响应体 → 尝试从请求体中提取目标 URL 并触发 sERP 采集
    target_url = _extract_collect_url(req_body, url, page_url)
    if target_url:
        logger.info(f"[dxm_capture] 触发自主采集: {target_url}")
        task_id = "collect_" + uuid_lib.uuid4().hex[:8]
        thread = threading.Thread(target=_run_collect_in_thread, args=(target_url, task_id), daemon=True)
        thread.start()
        return jsonify({"status": "ok", "task_id": task_id, "message": "已触发自主采集"}), 200

    return jsonify({"status": "ignored", "reason": "no product data found"}), 200


def _create_dxm_task(product_data):
    """创建店小秘截获产品任务"""
    task_id = "dxm_" + uuid_lib.uuid4().hex[:8]
    title = product_data.get("title", "店小秘采集")
    platform = product_data.get("platform", "unknown")
    image_count = product_data.get("image_count", 0)

    data_dir = os.path.join(DATA_ROOT, f"collect_{task_id}")
    os.makedirs(data_dir, exist_ok=True)

    product_data_file = os.path.join(data_dir, "product_data.json")
    with open(product_data_file, "w", encoding="utf-8") as f:
        json.dump(product_data, f, indent=2, ensure_ascii=False)

    collect_tasks[task_id] = {
        "status": "completed",
        "progress": 100,
        "message": f"店小秘截获 — {title[:40]}",
        "created_at": datetime.now().isoformat(),
        "result": {
            "title": title,
            "platform": platform,
            "url": product_data.get("url", ""),
            "image_count": image_count,
            "downloaded": 0,
            "failed": 0,
            "product_data": product_data_file.replace("\\", "/"),
            "images_mapping": None,
            "source": "mitm_dianxiaomi",
        },
    }
    _save_collect_tasks()
    logger.info(f"[dxm_capture] 店小秘采集: {title} (平台={platform}, 图片={image_count})")


def _extract_collect_url(req_body, api_url="", page_url=""):
    """从请求体中提取目标采集 URL"""
    if not isinstance(req_body, dict):
        return None

    # 常见字段: url, sourceUrl, productUrl, link, targetUrl
    for key in ("url", "sourceUrl", "productUrl", "link", "targetUrl", "originUrl"):
        val = req_body.get(key, "")
        if isinstance(val, str) and val.startswith("http"):
            return val

    # 嵌套: data.url
    data = req_body.get("data")
    if isinstance(data, dict):
        for key in ("url", "sourceUrl", "productUrl"):
            val = data.get(key, "")
            if isinstance(val, str) and val.startswith("http"):
                return val

    return None


def _log_dxm_capture(data, resp_body):
    """记录所有截获的请求到调试日志文件"""
    log_file = os.path.join(DATA_ROOT, "dxm_debug.jsonl")
    try:
        entry = {
            "timestamp": data.get("timestamp", ""),
            "url": data.get("url", ""),
            "method": data.get("method", ""),
            "status": data.get("status", ""),
            "pageUrl": data.get("pageUrl", ""),
            "response_type": type(resp_body).__name__,
            "response_preview": (
                resp_body if isinstance(resp_body, (dict, list))
                else str(resp_body)[:2000]
            ),
        }
        # 只记录可能包含产品数据的响应 (dict/list 有内容的)
        if isinstance(resp_body, dict) and resp_body:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        elif isinstance(resp_body, list) and resp_body:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _safe_get(obj, key, default=None):
    """Safe dict.get that works on non-dict types"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _extract_dxm_product(response_data, api_url: str = "", page_url: str = "") -> dict | None:
    """从店小秘 API 响应中提取产品数据"""
    if not isinstance(response_data, dict):
        return None

    # 尝试多种嵌套路径找产品数据
    data = response_data.get("data")
    result = response_data.get("result")

    candidates = [response_data]
    for v in [data, result]:
        if isinstance(v, dict):
            candidates.append(v)
            for sub_key in ("list", "rows", "records", "items", "products", "goods", "offers"):
                sub = v.get(sub_key)
                if isinstance(sub, list) and sub and isinstance(sub[0], dict):
                    candidates.append(sub[0])
                elif isinstance(sub, dict):
                    candidates.append(sub)
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            candidates.append(v[0])

    for candidate in candidates:
        title = (
            candidate.get("title")
            or candidate.get("productTitle")
            or candidate.get("productName")
            or candidate.get("goodsName")
            or candidate.get("name")
        )
        if not title:
            continue

        platform = "unknown"
        if candidate.get("platform"):
            platform = str(candidate["platform"]).lower()
        else:
            for key in ("ozonProductId", "ozon_product_id", "offer_id", "ozonItemId"):
                if key in candidate:
                    platform = "ozon"
                    break
            for key in ("wbProductId", "wildberries_product_id", "nmId"):
                if key in candidate:
                    platform = "wildberries"
                    break
            for key in ("asin", "amazonProductId"):
                if key in candidate:
                    platform = "amazon"
                    break

        images = []
        for img_key in ("images", "imageList", "productImages", "mainImages", "detailImages", "pics", "pictures"):
            imgs = candidate.get(img_key, [])
            if isinstance(imgs, list) and imgs:
                images = [i if isinstance(i, str) else i.get("url", "") for i in imgs]
                break
        if not images:
            for img_key in ("mainImage", "mainImg", "coverImage", "coverImg", "image", "pic"):
                img = candidate.get(img_key, "")
                if isinstance(img, str) and img.startswith("http"):
                    images = [img]
                    break

        product_url = (
            candidate.get("sourceUrl")
            or candidate.get("originUrl")
            or candidate.get("productUrl")
            or candidate.get("url")
            or api_url
            or page_url
            or ""
        )

        return {
            "title": str(title),
            "platform": platform,
            "url": str(product_url),
            "image_count": len(images),
            "images": images,
            "price": str(candidate.get("price") or candidate.get("productPrice") or ""),
            "sku": str(candidate.get("sku") or candidate.get("productSku") or ""),
            "raw_response": response_data,
        }

    return None


@app.route("/api/collect/<task_id>/status", methods=["GET"])
def get_collect_status(task_id):
    """查询采集任务状态"""
    task = collect_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    
    return jsonify({
        "task_id": task_id,
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "result": task["result"]
    })


@app.route("/api/collect/<task_id>/result", methods=["GET"])
def get_collect_result(task_id):
    """获取采集结果数据（含缩略图 URL）"""
    task = collect_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    if task["status"] != "completed":
        return jsonify({"error": "任务尚未完成", "status": task["status"]}), 400

    result = task["result"]

    # 读取 product_data.json
    product_data = {}
    if result and result.get("product_data"):
        try:
            with open(result["product_data"], "r", encoding="utf-8") as f:
                product_data = json.load(f)
        except:
            pass

    # 读取 images_mapping.json
    images_mapping = []
    if result and result.get("images_mapping"):
        try:
            with open(result["images_mapping"], "r", encoding="utf-8") as f:
                images_mapping = json.load(f)
        except:
            pass

    # 扫描实际图片文件生成 thumbnail_urls 和 variant_groups
    thumbnail_urls = []
    variant_groups = {}
    images_dir = result.get("images_dir", "")
    base_url = f"/collect_images/{task_id}"

    if images_dir and os.path.isdir(images_dir):
        # 查找子目录（变体结构: images/01_Name/）
        try:
            subdirs = sorted([
                d for d in os.listdir(images_dir)
                if os.path.isdir(os.path.join(images_dir, d))
            ])
            for sd in subdirs:
                sd_path = os.path.join(images_dir, sd)
                files = sorted([
                    f for f in os.listdir(sd_path)
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ])
                if files:
                    # 变体名: "01_Apricot" → "Apricot"
                    variant_name = sd.split("_", 1)[-1] if "_" in sd else sd
                    variant_groups[variant_name] = len(files)
                    for f in files[:6]:  # 每个变体最多取6张缩略图
                        rel_path = os.path.relpath(os.path.join(sd_path, f), os.path.dirname(images_dir))
                        thumbnail_urls.append(f"{base_url}/{rel_path.replace(os.sep, '/')}")
        except Exception:
            pass

        # 如果没有子目录，直接扫描 images/ 下的文件
        if not thumbnail_urls:
            try:
                files = sorted([
                    f for f in os.listdir(images_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ])[:12]
                for f in files:
                    thumbnail_urls.append(f"{base_url}/images/{f}")
            except Exception:
                pass

    return jsonify({
        "task_id": task_id,
        "summary": result,
        "product_data": product_data,
        "images_mapping": images_mapping,
        "thumbnail_urls": thumbnail_urls,
        "variant_groups": variant_groups,
    })


@app.route("/api/collect/<task_id>/open_folder", methods=["POST"])
def open_collect_folder(task_id):
    """打开采集任务文件夹"""
    from collector import _get_collect_dir
    folder = _get_collect_dir(task_id)
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    if os.name == 'nt':
        os.startfile(folder)
    else:
        if sys.platform == 'darwin':
            subprocess.Popen(['open', folder])
        else:
            subprocess.Popen(['xdg-open', folder])
    return jsonify({"status": "opened", "folder": folder})


@app.route("/api/collect/<task_id>/product_status", methods=["GET"])
def get_collect_product_status(task_id):
    """查询采集任务是否已保存为正式产品"""
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    for p in product_list:
        if p.get("source_task_id") == task_id:
            return jsonify({
                "saved": True,
                "skc": p["skc"],
                "skus": p["skus"],
                "category": p.get("category", ""),
                "title": p.get("title", "")
            })
    return jsonify({"saved": False})


@app.route("/api/collect/<task_id>", methods=["DELETE"])
def delete_collect_task(task_id):
    """删除采集任务（含数据文件和文件夹）"""
    task = collect_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    
    # 1. 从内存中删除
    if task_id in collect_tasks:
        del collect_tasks[task_id]
    
    # 2. 从持久化文件中删除
    _save_collect_tasks()
    
    # 3. 删除采集文件夹（含图片等数据）
    from collector import _get_collect_dir
    folder = _get_collect_dir(task_id)
    if os.path.exists(folder):
        import shutil
        shutil.rmtree(folder)
    
    return jsonify({"success": True, "task_id": task_id, "message": "采集任务已删除"})


@app.route("/api/collect/<task_id>/save_product", methods=["POST"])
def save_collect_product(task_id):
    """将采集数据保存为正式产品，自动分配 SKC/SKU"""
    task = collect_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    
    if task["status"] != "completed":
        return jsonify({"error": "任务尚未完成", "status": task["status"]}), 400
    
    # 检查是否已保存
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    for p in product_list:
        if p.get("source_task_id") == task_id:
            return jsonify({"error": "该产品已保存", "skc": p["skc"]}), 409
    
    result = task["result"]
    title = result.get("title", "未命名产品")
    
    # 读取 product_data.json 获取完整数据
    product_data = {}
    if result and result.get("product_data"):
        try:
            with open(result["product_data"], "r", encoding="utf-8") as f:
                product_data = json.load(f)
        except:
            pass
    
    # 生成 SKC
    skc, category_cn = _generate_skc(title)
    category_code = CATEGORY_CODES.get(category_cn, "OTHR")
    
    # 生成 SKU（从图片映射中提取变体信息）
    images_mapping = []
    if result and result.get("images_mapping"):
        try:
            with open(result["images_mapping"], "r", encoding="utf-8") as f:
                images_mapping = json.load(f)
        except:
            pass
    
    # 从图片映射中提取 SKU 变体
    skus = []
    if isinstance(images_mapping, dict):
        # 变体格式: {"Red": [{"index":0,...},...], "Blue": [...]}
        for variant_name in sorted(images_mapping.keys()):
            variant = variant_name.strip().upper()
            variant_slug = re.sub(r'[^A-Z0-9]', '', variant) or f"V{len(skus)+1:02d}"
            sku = f"{skc}-{variant_slug}"
            skus.append(sku)
    elif isinstance(images_mapping, list) and len(images_mapping) > 0:
        # 简单格式（无变体），创建一个带编号的 SKU
        skus.append(f"{skc}-01")

    if not skus:
        skus.append(f"{skc}-DEFAULT")
    
    # 构建正式产品数据
    images_dir = result.get("images_dir", "")
    thumbnail = ""
    if images_dir and os.path.exists(images_dir):
        for root, _dirs, files in os.walk(images_dir):
            for fname in sorted(files):
                if os.path.splitext(fname)[1].lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp'):
                    rel = os.path.relpath(os.path.join(root, fname), images_dir).replace('\\', '/')
                    thumbnail = f"/product_images/{skc}/{rel}"
                    break
            if thumbnail:
                break

    product_entry = {
        "skc": skc,
        "skus": skus,
        "title": title,
        "category": category_cn,
        "category_code": category_code,
        "source_task_id": task_id,
        "source_url": result.get("url", ""),
        "platform": result.get("platform", ""),
        "price": result.get("price", ""),
        "created_at": datetime.now().isoformat(),
        "product_data": product_data,
        "images_dir": images_dir,
        "thumbnail": thumbnail,
        "downloaded": result.get("downloaded", 0),
        "image_count": result.get("image_count", 0),
    }
    
    # 写入哈希表
    products_data["已注册编号"][skc] = title
    products_data["产品列表"].append(product_entry)
    _save_products(products_data)
    
    return jsonify({
        "success": True,
        "skc": skc,
        "skus": skus,
        "category": category_cn,
        "message": f"产品已保存为 {skc}"
    })


# 产品管理模块 API / extract_from_text 路由 已迁移到 DDD Product 域蓝图（见上方 register_blueprint）


@app.route("/api/stores", methods=["GET"])
def get_stores():
    """获取所有店铺列表"""
    return jsonify([_public_store(store) for store in _load_stores()])




# ==================== 店小秘自动填充 API ====================

@app.route("/api/auto-fill/analyze", methods=["POST"])
def auto_fill_analyze():
    """
    接收产品数据 + 店小秘页面表单字段列表，
    调用 DeepSeek 分析并返回字段映射填充建议。
    """
    data = request.get_json()
    skc = data.get("skc", "")
    product_title = data.get("product_title", "")
    product_data = data.get("product_data", {})
    manual_data = _effective_manual_data_for_fill(data.get("manual_data", {}))
    form_fields = data.get("form_fields", [])
    custom_prompts = data.get("custom_prompts", {})

    if not form_fields:
        return jsonify({"error": "表单字段列表不能为空"}), 400

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    DEEPSEEK_AUTO_FILL_MODEL = os.getenv("DEEPSEEK_AUTO_FILL_MODEL", "deepseek-v4-flash")

    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "DEEPSEEK_API_KEY not configured"}), 500

    # 构建产品信息摘要
    attrs = product_data.get("attributes", {})
    about_item = product_data.get("about_item", "")
    product_description = product_data.get("product_description", "")
    description = product_data.get("description", "")

    # 收集所有产品文本
    product_details = product_data.get("product_details", {})
    if product_details and isinstance(product_details, dict) and product_details.get("_raw"):
        del product_details["_raw"]
    brand = product_data.get("brand", "")
    category = product_data.get("category", "")
    rating = product_data.get("rating", "")
    variants = product_data.get("variants", {})

    # 从 product_details 中提取含单位的字段，生成换算提示
    unit_hints = []
    if product_details and isinstance(product_details, dict):
        weight_keys = [k for k in product_details.keys() if any(w in k.lower() for w in ["weight", "重量", "вес", "масса"])]
        dim_keys = [k for k in product_details.keys() if any(d in k.lower() for d in ["dimension", "size", "размер", "尺寸", "length", "長", "width", "寬", "height", "高", "depth", "深"])]
        unit_keys = weight_keys + dim_keys
        for k in unit_keys[:8]:
            val = product_details[k]
            if val and isinstance(val, str):
                val_lower = val.lower()
                hint = f"  - {k}: {val}"
                if any(u in val_lower for u in ["oz", "ounce", "盎司", "lb", "pound", "磅"]):
                    hint += " → 需换算为克(g): 1oz≈28.35g, 1lb≈453.6g"
                elif any(u in val_lower for u in ["in", "inch", "英寸", '"', "ft", "feet", "英尺"]):
                    hint += " → 需换算为厘米(cm): 1in≈2.54cm"
                unit_hints.append(hint)
        # 也检查 attributes 中的单位字段
        if attrs and isinstance(attrs, dict):
            for k, v in attrs.items():
                if isinstance(v, str) and any(u in v.lower() for u in ["oz", "lb", "in", "inch", "pound", "ounce"]):
                    unit_hints.append(f"  - {k}: {v} → 注意单位换算")

    product_texts = [
        "品牌: " + brand if brand else "",
        "品类: " + category if category else "",
        "评分: " + rating if rating else "",
        product_title,
        about_item,
        product_description,
        description,
        ("### 单位换算提醒（重点关注以下字段）\n" + "\n".join(unit_hints)) if unit_hints else "",
        "### 产品规格 (含原始单位，填充时注意换算)\n" + json.dumps(product_details, ensure_ascii=False, indent=2) if product_details else "",
    ]

    # 变体信息处理（优先使用结构化 variant_list）
    variant_list = data.get("variant_list", [])
    if variant_list:
        variant_text = "### 变体列表（结构化）\n"
        for i, v in enumerate(variant_list):
            variant_text += f"  变体{i+1}: 名称={v.get('name','')}, 价格={v.get('price','')}, "
            variant_text += f"库存={v.get('stock','')}, 属性={json.dumps(v.get('attributes',{}), ensure_ascii=False)}\n"
        product_texts.append(variant_text)
    else:
        # Fallback: old raw JSON format
        variants_fb = data.get("product_data", {}).get("variants", {})
        if variants_fb and variants_fb.get("values"):
            variant_text = "### 变体信息\n" + json.dumps(variants_fb, ensure_ascii=False, indent=2)
            product_texts.append(variant_text)

    # 提取确定性数据提示
    deterministic_hints = _prefill_deterministic(manual_data, product_data)
    hints_text = ""
    if deterministic_hints:
        hints_lines = [f"  - {k}: {v}" for k, v in deterministic_hints.items()]
        hints_text = "\n### 已知确定数据（优先使用）\n" + "\n".join(hints_lines)

    product_text = "\n".join(t for t in product_texts if t)

    # 构建表单字段摘要
    fields_summary = []
    for f in form_fields:
        label = f.get("label", "")
        placeholder = f.get("placeholder", "")
        tag = f.get("tag", "")
        ftype = f.get("type", "")
        name = f.get("name", "")
        options = f.get("options", [])
        fidx = f.get("index", len(fields_summary))

        field_desc = f"  [{fidx}] 标签: {label or name or '(无标签)'}"
        if placeholder:
            field_desc += f" | 占位: {placeholder}"
        if options:
            option_texts = []
            for o in options[:30]:
                if isinstance(o, dict):
                    option_texts.append(o.get("text") or o.get("value") or "")
                else:
                    option_texts.append(str(o))
            option_texts = [t for t in option_texts if t]
            if option_texts:
                field_desc += f" | 选项: {', '.join(option_texts)}"
        fields_summary.append(field_desc)
    valid_field_indices = set()
    for i, f in enumerate(form_fields):
        try:
            valid_field_indices.add(int(f.get("index", i)))
        except (TypeError, ValueError):
            valid_field_indices.add(i)

    field_by_index = {}
    for i, f in enumerate(form_fields):
        try:
            idx = int(f.get("index", i))
        except (TypeError, ValueError):
            idx = i
        field_by_index[idx] = f

    def _field_text_for_guard(field):
        if not field:
            return ""
        return " ".join(str(field.get(k, "") or "") for k in ("label", "placeholder", "name", "tag", "type")).lower()

    def _is_json_rich_field(field):
        text = _field_text_for_guard(field)
        if (field or {}).get("tag") == "json-editor":
            return True
        return any(k in text for k in ["json", "rich", "showcase", "富文本", "raShowcase", "витрина"])

    def _is_product_description_field(field):
        text = _field_text_for_guard(field)
        if _is_json_rich_field(field):
            return False
        return any(k in text for k in ["description", "desc", "描述", "说明", "описание", "аннотация"])

    def _looks_like_json_value(value):
        s = str(value or "").strip()
        if not s:
            return False
        if s[0] not in "{[":
            return False
        try:
            json.loads(s)
            return True
        except Exception:
            return s[0] == "{" and s[-1:] == "}"

    def _validate_mapping_value(field, value):
        if _is_json_rich_field(field):
            try:
                json.loads(str(value or "").strip())
                return True, ""
            except Exception:
                return False, "JSON rich-text field must receive valid JSON only"
        if _is_product_description_field(field) and _looks_like_json_value(value):
            return False, "product description must be natural language, not JSON rich-text content"
        return True, ""

    fields_text = "\n".join(fields_summary)

    # 拆分字段：重要字段 vs 常规字段
    IMPORTANT_LABEL_KW = [
        "название", "наименование", "name", "title", "名称", "标题", "полное название",
        "название товара", "наименование товара",
        "описание", "description", "描述", "说明", "аннотация", "описание товара",
        "hashtag", "хэштег", "тег", "тэг", "标签", "метка", "поисковые теги",
        "ключевые слова", "theme_tags",
        "rich", "showcase", "json", "富文本", "контент", "описание в формате",
        "раShowcase", "витрина",
    ]
    important_fields = []
    regular_fields = []
    for f in form_fields:
        label = (f.get("label", "") + " " + f.get("placeholder", "")).lower()
        if any(kw in label for kw in IMPORTANT_LABEL_KW):
            important_fields.append(f)
        else:
            regular_fields.append(f)

    system_prompt = """你是一个电商产品表单自动填充助手。你的任务是根据产品数据，为店小秘 Ozon 产品添加页面的表单字段提供填充值。

## 重要字段特殊规则
- 产品名称(название/name/title): 翻译为俄语，50-100字符，不包含品牌名，关键词前置
- 描述(описание/description): 4+1框架 —— 功能(1-2句) + 材质(1句) + 使用场景(1句) + 优势(1-2句) + 可选提示
- 标签(hashtag/хэштег): 生成10-22个标签，每个≤28字符，#开头，空格分隔。方法：核心词→长尾词→场景词→受众词→特征词
- 富文本(rich/json/showcase): 生成为raShowcase JSON格式

## 输入格式
你将收到：
1. 产品信息（标题、描述、属性等）
2. 表单字段列表（每个字段以 [序号] 开头，包含标签、占位符、选项等）
3. 变体列表 variant_list（结构化变体数据，含名称/价格/库存/属性）
4. 变体行映射 variant_row_summary（row_contexts 列表对应表单SKU行，variant_count 为应有变体数）
5. 表单字段标签可能包含 `[行上下文]`，用于区分多行SKU中相同名称的字段。例如 "统一计量单位中的商品数量 [红色, L]" 表示该字段属于红色L码变体行

## SKU多行填充规则
- variant_row_summary 中的 row_contexts 列表按表单SKU行顺序排列（第0行→第1行→...）
- variant_list 的第i个变体对应表单的第i个SKU行
- 每个SKU行的字段标签都带 `[行上下文]` 后缀，根据行上下文匹配对应变体的属性
- 如果缺少某变体的特定数据（如变体2无价格），用产品级数据或推断填充

## 字段标签说明
- 普通文本字段：标签如 "产品名称"、"重量, г"
- **checkbox-group**（多选组）：标签格式为 "属性名 (可选值: 选项A / 选项B / 选项C)"，从产品数据中判断哪些选项应勾选，**value 填应勾选的选项文本**（多个用逗号分隔，如 "天然皮革, 人造皮革"）。如果都不匹配则填 false
- **radio-group**（单选组）：标签格式为 "属性名 (选项: 选项A / 选项B / 选项C)"，从产品数据中判断应选哪个选项，**value 填应选中的选项文本**
- **select**（下拉框）：标签后可能包含 `| 选项: ...`，从选项列表中选取最接近的值

## 输出要求
请分析每个表单字段，判断它对应产品数据中的哪个信息，然后给出填充值。

### 字段匹配规则：
- **产品名称/标题** → 匹配标签含"名称""标题""name""title"的字段
- **产品描述** → 匹配标签含"描述""说明""description"的字段
- **价格** → 匹配标签含"价格""售价""price"的字段
- **重量** → 匹配标签含"重量""weight""重さ"的字段
- **尺寸/长宽高** → 匹配标签含"尺寸""长""宽""高""size""dimension"的字段
- **颜色** → 匹配标签含"颜色""color""colour"的字段
- **材质/材料** → 匹配标签含"材质""材料""material""leather"的字段，从产品标题/描述推断
- **品牌** → 匹配标签含"品牌""brand"的字段
- **分类/品类** → 匹配标签含"分类""品类""category"的字段
- **数量/件数/个数** → 匹配标签含"数量""库存""件数""个数""quantity""count""pcs"的字段，从产品描述或常识推断
- **对于 select 下拉框**：从选项列表中匹配最接近的值
- **对于 checkbox-group**：从"可选值"列表中选择匹配产品数据的选项文本，多个用逗号分隔
- **对于 radio-group**：从"选项"列表中选择最匹配产品数据的一个选项文本
- **对于其他字段**：根据标签和占位符推断

### 重要规则：
1. index 必须是表单字段列表里对应字段的 **[序号]** 值，直接填数字
2. 尽量为每个字段提供填充值，能推断的就推断（如皮革钱包 → 材质为"天然皮革"）
3. 对于下拉框(select)和选项组(checkbox-group/radio-group)，必须从提供的选项列表中选取值
4. 所有值必须是字符串
5. 明显无关的字段可跳过，但属性类字段尽量填充

## 单位换算规则
- 重量: 1 oz ≈ 28.35g, 1 lb ≈ 453.6g, 1 kg = 1000g。一律填写克(g)的纯数值
- 尺寸: 1 in ≈ 2.54cm。一律填写厘米(cm)的纯数值
- 若字段标签/placeholder已含单位(如"重量, г")，只填数值不含单位
- 若产品规格已是公制，直接使用
- 优先使用 manual_data.effective_weight_g / effective_size_spec；它们已按“实测优先，无实测用采集”的规则整理
- manual_data.cost_price 是产品实测成本价(CNY)，用于价格/利润判断，不能直接当作售价

请严格按照以下 JSON 格式返回，不要包含其他内容：
{"mappings": [{"index": <序号>, "value": "..."}, ...]}

其中 index 是表单字段列表中对应字段的 [序号] 数字，value 是要填充的值。"""

    # 构建自定义提示词段落
    system_prompt += """

## Hard validation contract
- Fields whose label/tag/type contains JSON, rich, showcase, 富文本, raShowcase, or json-editor are JSON rich-text fields. Fill them with valid JSON only.
- Fields whose label contains 产品描述, 描述, 说明, description, описание, or аннотация are normal product-description fields unless they are explicitly JSON rich-text fields. Fill them with natural language only.
- Never put raShowcase/JSON rich-text content into a normal product-description field.
- If both a normal product-description field and a JSON rich-text field exist, produce two different values: prose for the description field, JSON for the JSON field.
"""

    custom_prompt_block = ""
    if custom_prompts:
        parts = []
        for key, label in [("title", "产品标题"), ("description", "产品描述"), ("json_text", "JSON文本"), ("hashtag", "主题标签"), ("platform", "平台"), ("store", "店铺"), ("category", "品类")]:
            if custom_prompts.get(key):
                parts.append(f"### {label}填充提示\n{custom_prompts[key]}")
        if parts:
            custom_prompt_block = "\n## 用户自定义填充提示\n" + "\n\n".join(parts) + "\n"

    # 变体行映射信息
    variant_row_summary = data.get("variant_row_summary", {})
    variant_summary_block = ""
    if variant_row_summary:
        row_ctxs = variant_row_summary.get("row_contexts", [])
        vc = variant_row_summary.get("variant_count", 0)
        note = variant_row_summary.get("note", "")
        variant_summary_block = f"""
### 变体行映射
表单SKU行上下文: {json.dumps(row_ctxs, ensure_ascii=False)}
变体总数: {vc}
说明: {note}
"""

    user_prompt = f"""## 产品信息
SKC: {skc}
标题: {product_title}

### 产品描述文本
{product_text[:3000]}
{hints_text}
### 人工登记数据
{json.dumps(manual_data, ensure_ascii=False, indent=2)}
{custom_prompt_block}{variant_summary_block}
### 表单字段列表（共 {len(form_fields)} 个字段）
{fields_text}

请分析以上表单字段，为每个字段提供填充值。"""

    # ── 辅助函数：调用 DeepSeek 并解析返回 ──
    def _call_deepseek_fill(sys_prompt, usr_prompt, label="fill", model=None):
        model = model or DEEPSEEK_AUTO_FILL_MODEL
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"}
        }
        # v4-pro 禁用思考 token，跳过 chain-of-thought 直接输出 JSON
        if model == "deepseek-v4-pro":
            payload["thinking"] = {"type": "disabled"}
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code != 200:
                print(f"[auto-fill/{label}] API Error {resp.status_code}: {resp.text[:500]}")
                return []
            result = resp.json()
            choices = result.get("choices", [])
            if not choices:
                print(f"[auto-fill/{label}] no choices in response")
                return []
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or msg.get("reasoning_content", "")
            if not text:
                print(f"[auto-fill/{label}] empty content AND reasoning_content, msg keys: {list(msg.keys())}")
                return []

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start:end + 1]

            parsed = json.loads(cleaned)
            mappings = parsed.get("mappings", [])
            if not isinstance(mappings, list):
                if "format_retry" not in label:
                    retry_prompt = usr_prompt + "\n\n上一次返回未通过校验：mappings 必须是数组。请只返回 JSON：{\"mappings\":[{\"index\":0,\"value\":\"...\"}]}"
                    return _call_deepseek_fill(sys_prompt, retry_prompt, label + ":format_retry", model)
                print(f"[auto-fill/{label}] invalid mappings type")
                return []
            validated = []
            rejected = []
            for m in mappings:
                if isinstance(m, dict) and m.get("value"):
                    try:
                        m_index = int(m.get("index", -1))
                    except (TypeError, ValueError):
                        continue
                    if m_index not in valid_field_indices:
                        continue
                    value = str(m.get("value", ""))
                    ok_value, reason = _validate_mapping_value(field_by_index.get(m_index), value)
                    if not ok_value:
                        rejected.append({"index": m_index, "reason": reason})
                        continue
                    validated.append({
                        "index": m_index,
                        "label": m.get("label", ""),
                        "value": value
                    })
            if rejected and "format_retry" not in label:
                retry_prompt = usr_prompt + "\n\nPrevious response failed field validation: " + json.dumps(rejected, ensure_ascii=False) + "\nReturn JSON only. Keep normal product-description fields as natural-language prose. Put valid JSON only into JSON/rich/showcase/json-editor fields."
                return _call_deepseek_fill(sys_prompt, retry_prompt, label + ":format_retry", model)
            if rejected:
                print(f"[auto-fill/{label}] rejected mappings: {rejected}")
            print(f"[auto-fill/{label}] filled {len(validated)} fields")
            return validated
        except json.JSONDecodeError:
            print(f"[auto-fill/{label}] JSON parse failed, raw text (first 300 chars): {text[:300] if 'text' in dir() else 'N/A'}")
            if "format_retry" not in label:
                retry_prompt = usr_prompt + "\n\n上一次返回不是合法 JSON。请只返回 JSON：{\"mappings\":[{\"index\":0,\"value\":\"...\"}]}"
                return _call_deepseek_fill(sys_prompt, retry_prompt, label + ":format_retry", model)
            return []
        except Exception as e:
            print(f"[auto-fill/{label}] Exception: {e}")
            return []

    def _build_regular_system_prompt():
        return """你是电商产品表单填充助手，负责填充常规属性字段。

## 规则
1. select/checkbox-group/radio-group：从可选值中精确选取
2. 材质/颜色：根据产品数据填充
3. 重量/尺寸：填纯数字不含单位，优先用人工登记数据
4. 不确定的字段留空，不编造

返回 JSON: {"mappings": [{"index": <序号>, "value": "填充值"}, ...]}"""

    try:
        all_mappings = []

        if important_fields and regular_fields:
            # Parallel dual-batch: important + regular run concurrently
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_imp = executor.submit(
                    _call_deepseek_fill, system_prompt, user_prompt, "important"
                )
                future_reg = executor.submit(
                    _call_deepseek_fill, _build_regular_system_prompt(), user_prompt, "regular"
                )
                try:
                    imp_mappings = future_imp.result(timeout=150)
                    all_mappings.extend(imp_mappings)
                except Exception as e:
                    logger.warning("[auto-fill] important batch failed: %s", e)

                try:
                    reg_mappings = future_reg.result(timeout=150)
                    all_mappings.extend(reg_mappings)
                except Exception as e:
                    logger.warning("[auto-fill] regular batch failed: %s", e)

        if not all_mappings:
            # Unified fallback: all fields in one call
            all_mappings = _call_deepseek_fill(system_prompt, user_prompt, label="unified")

        # important 批次先进入，常规批次重复命中同一字段时不覆盖，避免二次错填。
        deduped_mappings = []
        seen_indices = set()
        for m in all_mappings:
            idx = m.get("index")
            if idx in seen_indices:
                continue
            seen_indices.add(idx)
            deduped_mappings.append(m)

        return jsonify({
            "success": True,
            "skc": skc,
            "mappings": deduped_mappings,
            "total_fields": len(form_fields),
            "filled_fields": len(deduped_mappings)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


# ==================== 上架草稿持久化 API ====================

LISTINGS_DIR = os.path.join(DATA_ROOT, "listings")
os.makedirs(LISTINGS_DIR, exist_ok=True)


def _listing_path(skc, store_id):
    """获取上架草稿文件路径"""
    safe_name = f"{skc}_{store_id}.json"
    return os.path.join(LISTINGS_DIR, safe_name)


@app.route("/api/listings/<skc>/<store_id>", methods=["GET"])
def get_listing(skc, store_id):
    """获取指定产品在指定店铺的上架草稿"""
    path = _listing_path(skc, store_id)
    if not os.path.exists(path):
        return jsonify({"exists": False, "listing": None})
    try:
        with open(path, "r", encoding="utf-8") as f:
            listing = json.load(f)
        return jsonify({"exists": True, "listing": listing})
    except:
        return jsonify({"exists": False, "listing": None})


@app.route("/api/listings/<skc>/<store_id>", methods=["PUT"])
def save_listing(skc, store_id):
    """保存/更新上架草稿"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "数据不能为空"}), 400
    
    data["skc"] = skc
    data["store_id"] = store_id
    data["updated_at"] = datetime.now().isoformat()
    
    path = _listing_path(skc, store_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return jsonify({"success": True, "updated_at": data["updated_at"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/listings/<skc>/<store_id>", methods=["DELETE"])
def delete_listing(skc, store_id):
    """删除上架草稿"""
    path = _listing_path(skc, store_id)
    if os.path.exists(path):
        try:
            os.remove(path)
        except:
            pass
    return jsonify({"success": True})


# ==================== Ozon API 集成 ====================

def _call_ozon_api(store_id, endpoint, payload=None, method="POST"):
    """调用 Ozon Seller API"""
    import time
    t_start = time.time()
    
    stores = _load_stores()
    store = next((s for s in stores if s["id"] == store_id), None)
    if not store:
        logger.error("[Ozon API] ❌ 店铺不存在: %s", store_id)
        return None, "店铺不存在"
    
    client_id = store.get("client_id", "")
    api_key = store.get("api_key", "")
    if not client_id or not api_key:
        logger.error("[Ozon API] ❌ 店铺未配置凭证: %s", store_id)
        return None, "店铺未配置 Ozon API 凭证"
    
    base_url = "https://api-seller.ozon.ru"
    url = f"{base_url}{endpoint}"
    
    headers = {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json"
    }
    
    payload_desc = ""
    if payload:
        # 在日志中只显示关键参数，不显示完整 payload（可能非常大）
        if "description_category_id" in payload:
            payload_desc = f" | category_id={payload['description_category_id']}"
        elif "attribute_id" in payload:
            payload_desc = f" | attr_id={payload['attribute_id']}"
    
    logger.info("[Ozon API] ➡️ 请求 %s %s%s | store=%s", method, endpoint, payload_desc, store_id)
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=30)
        else:
            resp = requests.post(url, headers=headers, json=payload or {}, timeout=30)
        
        elapsed = time.time() - t_start
        logger.info("[Ozon API] ⬅️ 响应 %s | 耗时 %.1fs | 数据大小: %s bytes", resp.status_code, elapsed, len(resp.content))
        
        if resp.status_code != 200:
            logger.error("[Ozon API] ❌ 错误: HTTP %s: %s", resp.status_code, resp.text[:300])
            return None, f"Ozon API Error {resp.status_code}: {resp.text[:500]}"
        
        return resp.json(), None
    except Exception as e:
        elapsed = time.time() - t_start
        logger.error("[Ozon API] ❌ 异常: %s | 耗时 %.1fs", e, elapsed)
        return None, str(e)



# ==================== 跨品类通用属性预设提示词库 ====================
# 根据 Ozon 属性名称（俄语/翻译后的中文）匹配预设填充规则
# 规则源自 Ozon 上架最佳实践

COMMON_ATTRIBUTE_PRESETS = {
    # ── 标题/名称类 ──
    "title_name": {
        "keywords": ["название", "наименование", "имя", "name", "title", "название товара",
                     "名称", "标题", "наименование товара", "полное название"],
        "instruction": """【标题填充 — 俄语优化规则】
从产品数据提取核心信息生成俄语标题：
1. 去除品牌名、删除商标符号（™®×•·）
2. 结构：商品类型 + 关键特征1 + 关键特征2 + 适用对象
3. 控制在 50~100 字符
4. 仅填俄语文本""",
    },
    # ── 描述类 ──
    "description": {
        "keywords": ["описание", "description", "аннотация", "描述", "说明",
                     "商品描述", "подробное описание", "описание товара"],
        "instruction": """【描述填充 — 4+1 结构化框架】
用俄语生成客观、信息型的结构化描述：
① 功能用途（1-2句）— 产品是什么、做什么
② 材质设计（1-2句）— 材料、工艺、结构
③ 适用场景（1句）— 什么人、什么场合使用
④ 优势特点（1-2句）— 差异化卖点
要求：禁止品牌名和特殊符号（— × • ™ ®）、每段≤4句、自然流畅""",
    },
    # ── 标签/Hashtag类 ──
    "hashtags": {
        "keywords": ["hashtag", "хэштег", "тег", "тэг", "标签", "метка",
                     "theme_tags", "поисковые теги", "ключевые слова"],
        "instruction": """【Ozon标签 — 5步法生成】
生成俄语标签（10~22个），每个≤28字符，#开头，空格分隔。
① 提取核心词：材质、功能、规格
② 对齐Ozon高频搜索词
③ 分组排序：功能类 > 用户群体类 > 场景类 > 节日类(可选)
④ 去重校验：不含品牌、不含特殊符号、独立有搜索意义
⑤ 输出一行：#тег1 #тег2 #тег3 ...
节日标签仅在距离节日≤2个月且产品适合送礼时加入1-3个""",
    },
    # ── 品牌类 ──
    "brand": {
        "keywords": ["brand", "бренд", "торговая марка", "марка", "品牌",
                     "производитель", "brand_name", "логотип"],
        "instruction": "从产品数据提取品牌名，无法确定时填「Нет бренда」。不编造品牌。",
    },
    # ── 材质类 ──
    "material": {
        "keywords": ["материал", "material", "состав", "材质", "材料", "ткань",
                     "материал верха", "подкладка", "материал корпуса", "основной материал"],
        "instruction": "从产品数据提取材质，翻译为俄语。dictionary类型从可选值中选最匹配的。常见：экокожа / натуральная кожа / полиуретан / силикон / металл / пластик / нейлон / полиэстер / хлопок / дерево",
    },
    # ── 颜色类 ──
    "color": {
        "keywords": ["цвет", "color", "colour", "颜色", "оттенок", "расцветка",
                     "основной цвет", "цвет товара"],
        "instruction": "从产品数据提取颜色，翻译为俄语。dictionary类型从可选值选最匹配的。常见：черный / белый / красный / синий / зеленый / коричневый / бежевый / серый / розовый / фиолетовый",
    },
    # ── 重量类 ──
    "weight": {
        "keywords": ["вес", "weight", "масса", "重量", "грамм", "килограмм",
                     "вес товара", "вес нетто", "вес в упаковке"],
        "instruction": "提取重量数值（克）。如果产品数据是kg则×1000转换。填入纯数字不含单位。优先使用人工登记数据中的 weight_g 字段。",
    },
    # ── 尺寸类 ──
    "dimensions": {
        "keywords": ["длина", "ширина", "высота", "глубина", "размер",
                     "length", "width", "height", "depth", "size",
                     "长度", "宽度", "高度", "深度", "尺寸", "габариты", "см"],
        "instruction": "提取尺寸数值（厘米）。多维度分别填写对应的长/宽/高字段。填入纯数字不含单位。优先使用人工登记数据。",
    },
    # ── 性别/受众类 ──
    "gender_audience": {
        "keywords": ["пол", "gender", "sex", "性别", "целевая аудитория",
                     "для кого", "мужской", "женский", "унисекс", "назначение"],
        "instruction": "推断目标用户：мужской(男) / женский(女) / унисекс(通用) / детский(儿童)。dictionary类型从可选值中选。不确定选унисекс。",
    },
    # ── 原产国 ──
    "country": {
        "keywords": ["страна", "country", "国家", "原产国", "производства",
                     "страна производства", "происхождения", "сделано в"],
        "instruction": "提取制造国（俄语全称）。无法确定时填「Китай」。常见：Китай / Россия / Турция / Индия / Вьетнам。",
    },
    # ── 数量/套装 ──
    "quantity": {
        "keywords": ["количество", "quantity", "数量", "комплект", "набор",
                     "в упаковке", "комплектация", "штук", "шт", "в наборе"],
        "instruction": "提取包装内产品数量，纯数字。套装/多件装填实际数量，无法确定填 1。",
    },
    # ── 保修 ──
    "warranty": {
        "keywords": ["гарантия", "warranty", "保修", "гарантийный срок",
                     "срок гарантии", "месяцев"],
        "instruction": "提取保修月数。电子类通常12个月，其他品类有明确数据再填。填纯数字。",
    },
    # ── 年龄/18+ ──
    "age": {
        "keywords": ["18+", "возраст", "age", "年龄", "ограничение",
                     "для взрослых", "возрастное ограничение"],
        "instruction": "判断是否成人用品。普通产品填 false/Нет，成人用品填 true/Да。",
    },
    # ── 系列/型号 ──
    "series_model": {
        "keywords": ["серия", "collection", "series", "коллекция", "系列",
                     "型号", "модель", "model", "линейка", "артикул"],
        "instruction": "提取产品系列/型号名，去除品牌名，仅保留型号标识。无明确型号则留空。",
    },
    # ── 闭合/扣件 ──
    "closure": {
        "keywords": ["застежка", "замок", "closure", "fastener", "扣件",
                     "闭合", "молния", "липучка", "кнопка", "тип застежки"],
        "instruction": "提取闭合方式翻译为俄语。常见：молния(拉链) / липучка(魔术贴) / кнопка(按扣) / магнит(磁吸) / клапан(翻盖) / шнуровка(系带)。dictionary类型从可选值选最匹配的。",
    },
    # ── 包装类型 ──
    "packaging": {
        "keywords": ["упаковка", "packaging", "包装", "тип упаковки",
                     "коробка", "пакет", "блистер", "вид упаковки"],
        "instruction": "推断包装方式：коробка(盒装) / пакет(袋装) / блистер(吸塑) / термоусадочная пленка(热缩膜)。不确定则留空。dictionary类型从可选值选。",
    },
}

# 非必填但跨品类通用的属性名称关键词 → 对应的 preset key
# 这些属性在大多数品类都会出现，虽然不是必填，但填了能提升 listing 质量
NON_REQUIRED_COMMON_ATTR_MAP = {
    # 属性名关键词 → preset key
    "hashtag": "hashtags",
    "хэштег": "hashtags",
    "тег": "hashtags",
    "标签": "hashtags",
    "коллекция": "series_model",
    "серия": "series_model",
    "系列": "series_model",
    "гарантия": "warranty",
    "保修": "warranty",
    "упаковка": "packaging",
    "包装": "packaging",
    "количество": "quantity",
    "комплект": "quantity",
    "数量": "quantity",
    "застежка": "closure",
    "扣件": "closure",
    "闭合": "closure",
    "молния": "closure",
    "возраст": "age",
    "18+": "age",
    "年龄": "age",
    "страна": "country",
    "原产": "country",
    "пол": "gender_audience",
    "性别": "gender_audience",
    "для кого": "gender_audience",
    "материал": "material",
    "材质": "material",
    "цвет": "color",
    "颜色": "color",
}


def _match_attribute_presets(ozon_attributes):
    """为每个 Ozon 属性匹配预设填充规则。
    返回: (preset_map, non_required_presets)
      - preset_map: {attr_id: instruction} — 所有匹配到的属性及其填充指令
      - non_required_presets: {attr_id: instruction} — 仅非必填且匹配到的属性
    """
    preset_map = {}
    non_required_presets = {}

    for attr in ozon_attributes:
        attr_id = attr.get("id")
        attr_name = attr.get("name", "") or ""
        attr_name_cn = attr.get("name_cn", "") or ""
        is_required = attr.get("is_required", False)

        instruction = None
        preset_key = None

        # 先做精确关键词匹配（中文翻译名优先于俄语名）
        search_text = f"{attr_name_cn} {attr_name}".lower()
        for key, preset in COMMON_ATTRIBUTE_PRESETS.items():
            for kw in preset["keywords"]:
                if kw.lower() in search_text:
                    instruction = preset["instruction"]
                    preset_key = key
                    break
            if instruction:
                break

        # 未匹配到完整 preset，但对非必填项尝试兜底匹配
        if not instruction and not is_required:
            for kw, preset_key in NON_REQUIRED_COMMON_ATTR_MAP.items():
                if kw.lower() in search_text:
                    instruction = COMMON_ATTRIBUTE_PRESETS.get(preset_key, {}).get("instruction", "")
                    break

        if instruction:
            preset_map[attr_id] = instruction
            if not is_required:
                non_required_presets[attr_id] = instruction

    return preset_map, non_required_presets


def _prefill_deterministic(manual_data, product_data):
    """从已有数据中提取可直接填入的确定值（不依赖 AI）。
    返回 {value_key: value} 用于后续 AI prompt 中提示。
    """
    hints = {}

    if manual_data:
        weight = manual_data.get("effective_weight_g") or manual_data.get("weight_g", "")
        if weight:
            hints["weight_g"] = str(weight)
            hints["weight_source"] = str(manual_data.get("effective_weight_source", "measured"))
        size_spec = manual_data.get("effective_size_spec") or manual_data.get("size_spec", "")
        if size_spec:
            hints["size_spec"] = str(size_spec)
            hints["size_source"] = str(manual_data.get("effective_size_source", "measured"))
        spec = manual_data.get("spec", "")
        if spec:
            hints["spec"] = str(spec)
        cost_price = manual_data.get("cost_price", "")
        if cost_price:
            hints["cost_price_cny"] = str(cost_price)

    if product_data:
        attrs = product_data.get("attributes", {}) or {}
        if isinstance(attrs, dict):
            for key, val in attrs.items():
                if val and isinstance(val, str):
                    kl = key.lower()
                    if any(kw in kl for kw in ["color", "colour"]):
                        hints["known_color"] = val
                    elif any(kw in kl for kw in ["material"]):
                        hints["known_material"] = val
                    elif any(kw in kl for kw in ["brand"]) and "нет бренда" not in val.lower():
                        hints["known_brand"] = val

    return hints


@app.route("/api/auto-fill/ozon-fields", methods=["POST"])
def auto_fill_ozon_fields():
    """
    接收产品数据 + Ozon 品类属性列表，
    分两批调用 DeepSeek 保证填写质量：
      Batch 1: 重要属性（标题/描述/标签/富文本）— 专用详细 prompt
      Batch 2: 常规属性（材质/颜色/重量等）— 通用 prompt
    """
    data = request.get_json()
    skc = data.get("skc", "")
    product_title = data.get("product_title", "")
    product_data = data.get("product_data", {})
    manual_data = data.get("manual_data", {})
    ozon_attributes = data.get("ozon_attributes", [])

    if not ozon_attributes:
        return jsonify({"error": "Ozon 属性列表不能为空"}), 400

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")

    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "DEEPSEEK_API_KEY not configured"}), 500

    # 1. 匹配预设填充规则
    preset_map, non_required_presets = _match_attribute_presets(ozon_attributes)

    # 2. 提取确定性数据
    deterministic_hints = _prefill_deterministic(manual_data, product_data)

    # 构建产品信息摘要
    about_item = product_data.get("about_item", "")
    product_description = product_data.get("product_description", "")
    description_text = product_data.get("description", "")
    product_texts = [product_title, about_item, product_description, description_text]
    product_text = "\n".join(t for t in product_texts if t)

    # ── 3. 拆分属性：重要属性 → 单独批次，常规属性 → 批量处理 ──
    IMPORTANT_KEYWORDS = [
        # 标题/名称类
        "название", "наименование", "name", "title", "名称", "标题", "полное название",
        "название товара", "наименование товара",
        # 描述类
        "описание", "description", "描述", "说明", "аннотация", "описание товара",
        # 标签类
        "hashtag", "хэштег", "тег", "тэг", "标签", "метка", "поисковые теги",
        "ключевые слова", "theme_tags",
        # 富文本类
        "rich", "showcase", "json", "富文本", "контент", "описание в формате",
        "раShowcase", "витрина",
    ]

    important_attrs = []
    regular_attrs = []
    for attr in ozon_attributes:
        name_text = f"{attr.get('name', '')} {attr.get('name_cn', '')}".lower()
        if any(kw in name_text for kw in IMPORTANT_KEYWORDS):
            important_attrs.append(attr)
        else:
            regular_attrs.append(attr)

    logger.info("[自动填充] 属性拆分 | 重要=%s | 常规=%s | skc=%s",
                len(important_attrs), len(regular_attrs), skc)

    # ── 辅助函数：调用 DeepSeek 并解析返回 ──
    def _call_deepseek_fill(sys_prompt, user_prompt, label="fill", model="deepseek-v4-pro"):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"}
        }
        # v4-pro 禁用思考 token，跳过 chain-of-thought 直接输出 JSON
        if model == "deepseek-v4-pro":
            payload["thinking"] = {"type": "disabled"}
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code != 200:
                logger.warning("[自动填充/%s] API Error %s: %s", label, resp.status_code, resp.text[:500])
                return []
            result = resp.json()
            choices = result.get("choices", [])
            if not choices:
                logger.warning("[自动填充/%s] no choices in response")
                return []
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or msg.get("reasoning_content", "")
            if not text:
                logger.warning("[自动填充/%s] empty content AND reasoning_content, msg keys: %s", label, list(msg.keys()))
                return []

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start:end + 1]

            parsed = json.loads(cleaned)
            mappings = parsed.get("mappings", [])
            validated = []
            for m in mappings:
                if isinstance(m, dict) and "attribute_id" in m:
                    validated.append({
                        "attribute_id": m.get("attribute_id"),
                        "value": str(m.get("value", ""))
                    })
            logger.info("[自动填充/%s] ✅ 填充 %s 个属性", label, len(validated))
            return validated
        except json.JSONDecodeError:
            logger.warning("[自动填充/%s] JSON 解析失败: %s", label, text[:300] if 'text' in dir() else 'N/A')
            return []
        except Exception as e:
            logger.error("[自动填充/%s] 异常: %s", label, e)
            return []

    # ── 确定性数据提示 ──
    hints_text = ""
    if deterministic_hints:
        hints_lines = [f"  - {k}: {v}" for k, v in deterministic_hints.items()]
        hints_text = "\n### 已知确定数据（优先使用）\n" + "\n".join(hints_lines)

    all_mappings = []
    important_count = 0
    regular_count = 0

    # ── 构建批次 prompt 的函数 ──
    def _build_important_batch():
        imp_summary = []
        for attr in important_attrs:
            label = f"ID:{attr.get('id')} 名称:{attr.get('name')}"
            cn = attr.get('name_cn', '')
            if cn:
                label += f"（{cn}）"
            label += f" 类型:{attr.get('type')} {'🔴必填' if attr.get('is_required') else '⚪选填'}"
            if attr.get("dictionary_values"):
                vals = [v.get("value", "") for v in attr["dictionary_values"][:30]]
                label += f" 可选值: [{', '.join(vals)}]"
            if attr.get("id") in preset_map:
                label += f"\n    📋 专用指引: {preset_map[attr.get('id')]}"
            imp_summary.append(label)

        imp_system = """你是俄罗斯电商平台（Ozon/Wildberries）的资深内容优化专家。

## 任务
你正在处理的是**重要属性**（标题/描述/标签/富文本），这些属性直接影响商品的搜索排名和转化率。

## 标题类属性填充规则
- 俄语撰写，50~100字符
- 结构：商品类型 + 关键特征（材质/功能） + 适用对象
- 严禁品牌名和特殊符号（™®×•·）
- 使用Ozon/WB平台高频搜索词

## 描述类属性填充规则（4+1框架）
- ① 功能用途 — 1~2句说明产品是什么、做什么
- ② 材质设计 — 材料、工艺、结构
- ③ 适用场景 — 什么人、什么场合
- ④ 优势特点 — 差异化卖点
- ⑤（可选）使用提示
- 客观语气，每段≤4句，俄语撰写

## 标签/Hashtag类属性填充规则（5步法）
- ① 提取核心词（材质、功能、规格）
- ② 对齐Ozon高频搜索词
- ③ 分组排序：功能类 > 用户群体类 > 场景类 > 节日类(可选)
- ④ 每个标签≤28字符，#开头，不含品牌
- ⑤ 10~22个标签，一行空格分隔
- 节日标签：仅距离节日≤2个月且产品适合送礼时加1-3个

## 富文本/JSON类属性填充规则
- 如属性为raShowcase JSON格式，生成标准 {"version": 0.3, "content": [...]} 结构
- 所有文字俄语，自然流畅

## 通用约束
- dictionary类型必须从可选值中精确选取
- 不确定的字段可留空，不编造
- 返回 JSON: {"mappings": [{"attribute_id": 123, "value": "填充值"}, ...]}"""

        imp_user = f"""## 产品信息
SKC: {skc}
标题: {product_title}
产品文本: {product_text[:3000]}
{hints_text}
人工登记: {json.dumps(manual_data, ensure_ascii=False, indent=2)}

## 重要属性列表（共 {len(important_attrs)} 个，请逐一高质量填充）
{chr(10).join(imp_summary)}

请为以上每个属性提供高质量填充值。"""
        return _call_deepseek_fill(imp_system, imp_user, label="重要属性")

    def _build_regular_batch():
        reg_summary = []
        for attr in regular_attrs:
            label = f"ID:{attr.get('id')} 名称:{attr.get('name')}"
            cn = attr.get('name_cn', '')
            if cn:
                label += f"（{cn}）"
            label += f" 类型:{attr.get('type')} {'🔴必填' if attr.get('is_required') else '⚪选填'}"
            if attr.get("dictionary_values"):
                vals = [v.get("value", "") for v in attr["dictionary_values"][:30]]
                label += f" 可选值: [{', '.join(vals)}]"
            if attr.get("id") in preset_map:
                label += f"\n    📋 指引: {preset_map[attr.get('id')]}"
            reg_summary.append(label)

        reg_system = """你是 Ozon/Wildberries 商品上架助手，负责填充常规属性。

## 规则
1. dictionary类型：从可选值中精确选取
2. 材质/颜色：翻译为俄语，dictionary则从列表中选
3. 重量/尺寸：填纯数字不含单位，优先用人工登记数据
4. 原产国：默认"Китай"
5. 不确定的字段留空，不编造

返回 JSON: {"mappings": [{"attribute_id": 123, "value": "填充值"}, ...]}"""

        reg_user = f"""## 产品信息
SKC: {skc}
标题: {product_title}
产品文本: {product_text[:3000]}
{hints_text}
人工登记: {json.dumps(manual_data, ensure_ascii=False, indent=2)}

## 常规属性列表（共 {len(regular_attrs)} 个）
{chr(10).join(reg_summary)}

请为以上每个属性提供填充值。"""
        return _call_deepseek_fill(reg_system, reg_user, label="常规属性")

    # ── 并行执行两个批次 ──
    if important_attrs and regular_attrs:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_imp = executor.submit(_build_important_batch)
            future_reg = executor.submit(_build_regular_batch)
            try:
                batch1 = future_imp.result(timeout=150)
                all_mappings.extend(batch1)
                important_count = len(batch1)
            except Exception as e:
                logger.warning("[自动填充] 重要属性批次失败: %s", e)

            try:
                batch2 = future_reg.result(timeout=150)
                all_mappings.extend(batch2)
                regular_count = len(batch2)
            except Exception as e:
                logger.warning("[自动填充] 常规属性批次失败: %s", e)
    elif important_attrs:
        batch1 = _build_important_batch()
        all_mappings.extend(batch1)
        important_count = len(batch1)
    elif regular_attrs:
        batch2 = _build_regular_batch()
        all_mappings.extend(batch2)
        regular_count = len(batch2)

    # ── 汇总返回 ──
    logger.info("[自动填充] 完成 | skc=%s | 重要=%s/%s | 常规=%s/%s | 合计=%s",
                skc, important_count, len(important_attrs),
                regular_count, len(regular_attrs), len(all_mappings))

    return jsonify({
        "success": True,
        "skc": skc,
        "mappings": all_mappings,
        "total_attributes": len(ozon_attributes),
        "filled_attributes": len(all_mappings),
        "important_count": len(important_attrs),
        "regular_count": len(regular_attrs),
        "preset_matched": len(preset_map),
        "non_required_presets": len(non_required_presets),
        "deterministic_hints": list(deterministic_hints.keys())
    })


# ==================== Ozon 产品创建 API ====================

OZON_LISTING_SCORE_TARGET = 80


def _to_float(value, default=0.0):
    try:
        if value is None:
            return default
        text = str(value).strip().replace(",", ".")
        if not text:
            return default
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else default
    except Exception:
        return default


def _is_public_product_image_url(url):
    if not isinstance(url, str):
        return False
    value = url.strip()
    low = value.lower()
    if not low.startswith(("http://", "https://")):
        return False
    if low.endswith(".svg") or "sprite" in low or "aicid=community" in low:
        return False
    if any(token in low for token in ("_ss64_", "_us40_", "_uc154", "_sr89", "_sr166", "_ul165", "_ul330", "_ul495")):
        return False
    if not any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return False
    return True


def _extract_public_image_urls(images, limit=10):
    urls = []
    seen = set()
    for img in images or []:
        url = img.get("url", "") if isinstance(img, dict) else str(img)
        if not _is_public_product_image_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _find_product_by_skc(skc):
    if not skc:
        return None
    try:
        products_data = _load_products()
    except Exception:
        return None
    for product in products_data.get("产品列表", []) + products_data.get("浜у搧鍒楄〃", []):
        if product.get("skc") == skc:
            return product
    return None


def _default_skus_from_product(skc, price):
    product = _find_product_by_skc(skc)
    if not product:
        return []
    result = []
    default_price = str(price or product.get("price") or "")
    for sku in product.get("skus") or []:
        result.append({
            "name": sku,
            "sku_code": sku,
            "price": default_price,
            "old_price": "",
            "stock": "10000",
            "barcode": "",
            "images": [],
        })
    return result


def _score_ozon_listing_payload(data):
    issues = []
    warnings = []
    sections = []

    def add_section(name, points, max_points, detail):
        sections.append({"name": name, "points": points, "max_points": max_points, "detail": detail})

    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    price = _to_float(data.get("price"))
    offer_id = str(data.get("offer_id", "")).strip()
    category_id = data.get("category_id")
    type_id = data.get("type_id")
    attrs = data.get("attributes") or []
    skus = data.get("skus") or _default_skus_from_product(data.get("skc"), price)
    rich_content = data.get("rich_content") or []

    category_points = 10 if category_id else 0
    if not category_id:
        issues.append("缺少 Ozon 类目 description_category_id")
    if type_id:
        category_points += 5
    else:
        warnings.append("缺少 type_id，部分 Ozon 类目可能导入失败")
    add_section("类目", category_points, 15, "类目 ID 与 type_id")

    basic_points = 0
    if 20 <= len(name) <= 200:
        basic_points += 6
    elif name:
        basic_points += 3
        warnings.append("商品标题长度不理想，建议 20-200 字符")
    else:
        issues.append("缺少商品标题")
    if len(description) >= 300:
        basic_points += 5
    elif description:
        basic_points += 2
        warnings.append("商品描述偏短，建议补充用途、材质、容量、RFID 等卖点")
    else:
        issues.append("缺少商品描述")
    if offer_id:
        basic_points += 2
    else:
        issues.append("缺少主 offer_id")
    if price > 0:
        basic_points += 2
    else:
        issues.append("缺少有效售价")
    add_section("基础信息", basic_points, 15, "标题、描述、offer_id、售价")

    filled_attrs = [a for a in attrs if a.get("attribute_id") and str(a.get("value", "")).strip()]
    attr_points = min(18, len(filled_attrs) * 1.2)
    attr_text = json.dumps(attrs, ensure_ascii=False).lower()
    if any(token in attr_text for token in ("материал", "material", "экокожа", "5309")):
        attr_points += 2
    else:
        warnings.append("未识别到材料属性，wallet 类目建议必填")
    if any(token in attr_text for token in ("цвет", "color", "10096", "10097")):
        attr_points += 2
    else:
        warnings.append("未识别到颜色属性，变体商品建议补齐")
    if any(token in attr_text for token in ("бренд", "brand", "\"85\"")):
        attr_points += 1.5
    if rich_content:
        attr_points += 1.5
    else:
        warnings.append("缺少 Rich Content/JSON 富文本，会影响卡片质量")
    attr_points = min(25, attr_points)
    if attr_points < 15:
        issues.append("Ozon 属性填写不足，建议先拉取类目必填属性并补齐")
    add_section("属性完整度", round(attr_points, 1), 25, f"已填属性 {len(filled_attrs)} 个")

    raw_images = data.get("images") or []
    base_image_urls = _extract_public_image_urls(raw_images, 10)
    rejected_images = max(0, len(raw_images) - len(base_image_urls))
    media_points = min(15, len(base_image_urls) * 3)
    if len(base_image_urls) >= 5:
        media_points += 3
    if rich_content:
        media_points += 2
    if not base_image_urls:
        issues.append("没有可提交到 Ozon 的公网商品图片 URL")
    elif rejected_images:
        warnings.append(f"已过滤 {rejected_images} 张非商品图/缩略图/图标")
    add_section("媒体素材", min(20, media_points), 20, f"可用主图 {len(base_image_urls)} 张")

    sku_points = 0
    valid_skus = []
    sku_offer_ids = set()
    for sku in skus:
        sku_id = str(sku.get("sku_code") or sku.get("name") or "").strip()
        sku_price = _to_float(sku.get("price") or data.get("price"))
        if sku_id and sku_price > 0:
            valid_skus.append(sku)
        if sku_id:
            sku_offer_ids.add(sku_id)
    if skus and len(valid_skus) == len(skus):
        sku_points += 8
    elif valid_skus:
        sku_points += 4
        warnings.append("部分 SKU 缺少 offer_id 或价格")
    else:
        issues.append("缺少可提交的 SKU/变体")
    if len(sku_offer_ids) == len(skus) and skus:
        sku_points += 3
    else:
        warnings.append("SKU offer_id 为空或重复")
    if skus and all(_to_float(s.get("stock"), -1) >= 0 for s in skus):
        sku_points += 2
    else:
        warnings.append("部分 SKU 缺少库存")
    if len(skus) >= 2:
        sku_points += 2
    add_section("变体与库存", min(15, sku_points), 15, f"SKU {len(skus)} 个")

    ops_points = 0
    if price > 0:
        ops_points += 3
    if any(_to_float(s.get("old_price")) > _to_float(s.get("price")) > 0 for s in skus):
        ops_points += 2
    else:
        warnings.append("未识别到有效原价，建议原价高于售价")
    if re.search(r"(4383|weight|вес)", attr_text):
        ops_points += 2
    else:
        warnings.append("缺少重量属性，wallet 当前应优先使用实测重量")
    if re.search(r"(height|width|depth|length|尺寸|размер|5355|5299|6573)", attr_text):
        ops_points += 2
    else:
        warnings.append("缺少尺寸属性，Ozon 物流和审核可能受影响")
    if data.get("barcode") or any(str(s.get("barcode", "")).strip() for s in skus):
        ops_points += 1
    else:
        warnings.append("未填写条码；如 Ozon 允许自动生成，可后续补")
    add_section("价格物流", min(10, ops_points), 10, "价格、原价、重量、尺寸、条码")

    score = round(sum(float(s["points"]) for s in sections))
    return {
        "score": score,
        "target_score": OZON_LISTING_SCORE_TARGET,
        "can_submit": score >= OZON_LISTING_SCORE_TARGET and not issues,
        "sections": sections,
        "issues": issues,
        "warnings": warnings,
        "filtered_image_count": len(base_image_urls),
        "rejected_image_count": rejected_images,
    }


def _append_listing_lifecycle_event(skc, store_id, event):
    if not skc or not store_id:
        return
    path = _listing_path(skc, store_id)
    listing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                listing = json.load(f)
        except Exception:
            listing = {}
    lifecycle = listing.get("lifecycle")
    if not isinstance(lifecycle, list):
        lifecycle = []
    entry = {"at": datetime.now().isoformat(timespec="seconds")}
    entry.update(event)
    lifecycle.append(entry)
    listing["lifecycle"] = lifecycle[-50:]
    listing["updated_at"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(listing, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("[Ozon lifecycle] failed to persist event: %s", exc)


@app.route("/api/ozon/<store_id>/listing/simulate", methods=["POST"])
def ozon_listing_simulate(store_id):
    data = request.get_json() or {}
    skc = data.get("skc", "")
    report = _score_ozon_listing_payload(data)
    _append_listing_lifecycle_event(skc, store_id, {
        "event": "simulate",
        "score": report["score"],
        "can_submit": report["can_submit"],
        "issues": report["issues"],
        "warnings": report["warnings"][:5],
    })
    return jsonify({"success": True, "store_id": store_id, "skc": skc, "report": report})


@app.route("/api/ozon/<store_id>/product/create", methods=["POST"])
def ozon_product_create(store_id):
    """调用 Ozon /v3/product/import 创建产品（支持多变种批量上传）"""
    data = request.get_json()
    skc = data.get("skc", "")
    name = data.get("name", "")
    description = data.get("description", "")
    price = data.get("price", "")
    offer_id = data.get("offer_id", "")
    barcode = data.get("barcode", "")
    category_id = data.get("category_id", 0)
    type_id = data.get("type_id")
    attrs = data.get("attributes", [])
    images = data.get("images", [])
    videos = data.get("videos", [])
    skus = data.get("skus", []) or _default_skus_from_product(skc, price)
    quality_report = _score_ozon_listing_payload(data)

    logger.info("[产品创建] ========== 开始创建产品 ==========")
    logger.info("[产品创建] skc=%s | name=%s | price=%s | category_id=%s | type_id=%s | SKU数=%s",
                skc, name, price, category_id, type_id, len(skus))

    if not quality_report["can_submit"]:
        _append_listing_lifecycle_event(skc, store_id, {
            "event": "quality_gate_failed",
            "score": quality_report["score"],
            "issues": quality_report["issues"],
            "warnings": quality_report["warnings"][:5],
        })
        return jsonify({
            "success": False,
            "error": f"Ozon 模拟上架评分 {quality_report['score']}，未达到 {OZON_LISTING_SCORE_TARGET} 分或存在阻断问题",
            "quality_report": quality_report,
        }), 400

    if not name or not price:
        logger.warning("[产品创建] ❌ 缺少必填字段")
        return jsonify({"success": False, "error": "产品名称、价格为必填项"}), 400

    if not category_id:
        logger.warning("[产品创建] ❌ 缺少品类ID")
        return jsonify({"success": False, "error": "请先匹配产品品类"}), 400

    # 格式化属性为 Ozon API 格式（所有 SKU 共用）
    ozon_attrs = []
    for attr in attrs:
        attr_id = attr.get("attribute_id")
        value = attr.get("value", "")
        attr_type = attr.get("type", "text")

        if not attr_id:
            continue

        entry = {"id": int(attr_id), "values": []}
        if attr_type == "dictionary":
            try:
                dict_val_id = int(value)
                entry["values"].append({"dictionary_value_id": dict_val_id})
            except (ValueError, TypeError):
                entry["values"].append({"value": str(value)})
        else:
            entry["values"].append({"value": str(value)})
        ozon_attrs.append(entry)

    # 公共图片（base64 或本地路径会被过滤，仅传 http URL）
    base_image_urls = _extract_public_image_urls(images, 10)

    # 公共视频
    base_video_urls = [v.get("url", "") for v in videos if v.get("url", "").startswith("http")]

    def _build_item(sku_price, sku_offer_id, sku_barcode, sku_images):
        """构建单个 Ozon product import item"""
        item = {
            "name": name,
            "offer_id": sku_offer_id,
            "price": sku_price or price,
            "currency_code": "CNY",
            "description_category_id": int(category_id),
            "attributes": ozon_attrs,
            "vat": "0",
        }
        if type_id and str(type_id) != str(category_id):
            item["type_id"] = int(type_id)
        if description:
            item["description"] = description[:2000]
        if sku_barcode:
            item["barcode"] = sku_barcode

        # SKU 独立图片优先，否则用公共图片
        sku_urls = _extract_public_image_urls(sku_images, 10)
        item_images = sku_urls if sku_urls else base_image_urls
        if item_images:
            item["images"] = item_images
        if base_video_urls:
            item["videos"] = base_video_urls

        logger.info("[产品创建]   子产品: offer_id=%s | price=%s | images=%s | videos=%s", sku_offer_id, item["price"], len(item_images), len(base_video_urls))
        return item

    # 构建 items 数组
    items = []
    if skus:
        # 多变种模式：每个 SKU 生成一个 item
        for sku in skus:
            sku_price = sku.get("price", "")
            sku_barcode_val = sku.get("barcode", "")
            sku_images = sku.get("images", [])
            sku_offer_id = sku.get("name", "") or offer_id

            if not sku_offer_id:
                logger.warning("[产品创建] ⚠️ 跳过空 offer_id 的 SKU")
                continue

            item = _build_item(sku_price, sku_offer_id, sku_barcode_val, sku_images)
            items.append(item)
    else:
        # 单产品模式（向后兼容）
        if not offer_id:
            logger.warning("[产品创建] ❌ 缺少 offer_id")
            return jsonify({"success": False, "error": "Offer ID 为必填项"}), 400
        items.append(_build_item(price, offer_id, barcode, []))

    if not items:
        logger.warning("[产品创建] ❌ 没有可提交的产品")
        return jsonify({"success": False, "error": "没有可提交的产品变种"}), 400

    logger.info("[产品创建] 📦 共 %s 个 item，attributes=%s", len(items), len(ozon_attrs))

    payload = {"items": items}
    result, err = _call_ozon_api(store_id, "/v3/product/import", payload)

    if err:
        logger.error("[产品创建] ❌ 创建失败: %s", err)
        user_msg = err
        try:
            err_data = json.loads(err.replace("Ozon API Error 400: ", "").replace("Ozon API Error 500: ", ""))
            if isinstance(err_data, dict):
                if "message" in err_data:
                    user_msg = err_data["message"]
                elif "details" in err_data:
                    details = err_data["details"]
                    if isinstance(details, list) and details:
                        user_msg = "; ".join(str(d.get("message", d)) for d in details[:3])
        except:
            pass
        _append_listing_lifecycle_event(skc, store_id, {
            "event": "ozon_import_failed",
            "score": quality_report["score"],
            "error": user_msg,
        })
        return jsonify({"success": False, "error": f"Ozon 上架失败: {user_msg}", "quality_report": quality_report}), 502

    task_id = result.get("result", {}).get("task_id", "")
    logger.info("[产品创建] ✅ 提交成功！task_id=%s | items=%s", task_id, len(items))
    _append_listing_lifecycle_event(skc, store_id, {
        "event": "ozon_import_submitted",
        "mode": "upsert",
        "score": quality_report["score"],
        "task_id": task_id,
        "item_count": len(items),
    })

    return jsonify({
        "success": True,
        "task_id": task_id,
        "skc": skc,
        "item_count": len(items),
        "quality_report": quality_report,
        "message": f"已提交 {len(items)} 个产品变种到 Ozon（任务ID: {task_id}），请稍后在 Ozon 后台查看上架状态。"
    })


@app.route("/api/ozon/<store_id>/sync-products", methods=["POST"])
def ozon_sync_products(store_id):
    """从 Ozon 店铺拉取产品状态，匹配并更新本地产品库"""
    logger.info("[产品同步] ========== 开始同步 ==========")
    logger.info("[产品同步] store_id=%s", store_id)

    # ===== PULL 阶段: 拉取 Ozon 产品状态 =====
    # Step 1: 分页获取全量 offer_id
    all_offer_ids = []
    last_id = ""
    page = 0
    while True:
        page += 1
        payload = {"limit": 100, "filter": {"visibility": "ALL"}}
        if last_id:
            payload["last_id"] = last_id

        result, err = _call_ozon_api(store_id, "/v3/product/list", payload)
        if err:
            logger.error("[产品同步] ❌ 获取产品列表失败 (第%s页): %s", page, err)
            return jsonify({"success": False, "error": f"获取 Ozon 产品列表失败: {err}"}), 502

        items = (result or {}).get("result", {}).get("items", [])
        total = (result or {}).get("result", {}).get("total", 0)
        for item in items:
            oid = item.get("offer_id", "")
            if oid:
                all_offer_ids.append(oid)
        logger.info("[产品同步] 第%s页: %s 个 | 累计: %s/%s", page, len(items), len(all_offer_ids), total)

        last_id = (result or {}).get("result", {}).get("last_id", "")
        if not last_id or len(items) == 0:
            break

    # Step 2: 批量获取产品详情（含 statuses）
    all_info_items = []
    for i in range(0, len(all_offer_ids), 100):
        batch = all_offer_ids[i:i+100]
        result, err = _call_ozon_api(store_id, "/v3/product/info/list",
                                     {"offer_id": batch})
        if err:
            logger.error("[产品同步] ❌ 获取产品详情失败: %s", err)
            return jsonify({"success": False, "error": f"获取产品详情失败: {err}"}), 502
        batch_items = (result or {}).get("items", [])
        all_info_items.extend(batch_items)

    logger.info("[产品同步] 获取 %s 个产品详情", len(all_info_items))

    # Step 3: 加载本地产品，建立 offer_id 索引
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])

    offer_index = {}
    for pi, p in enumerate(product_list):
        for sku in (p.get("skus") or []):
            offer_index[sku] = {"skc": p["skc"], "idx": pi}

    # Step 4: 匹配 & 更新状态
    matched = 0
    new_skus = 0
    updated = 0
    synced = []

    for info in all_info_items:
        offer_id = info.get("offer_id", "")
        product_id = info.get("product_id") or info.get("id", 0)
        name = info.get("name", "")
        statuses = info.get("statuses", {})
        is_archived = info.get("is_archived") or info.get("is_autoarchived")

        if not offer_id:
            continue

        # 映射 Ozon 复合状态到本地 4 状态
        moderate = statuses.get("moderate_status", "")
        ozon_status = statuses.get("status", "")
        if is_archived:
            mapped_status = "已下架"
        elif moderate == "approved":
            mapped_status = "已上架"
        elif moderate == "declined":
            mapped_status = "审核拒绝"
        elif ozon_status == "new":
            mapped_status = "审核中"
        else:
            mapped_status = "已上架" if ozon_status == "price_sent" else ozon_status

        entry = offer_index.get(offer_id)
        if entry:
            skc = entry["skc"]
            p = product_list[entry["idx"]]
            if "store_status" not in p:
                p["store_status"] = {}
            old_status = p["store_status"].get(store_id, "")
            p["store_status"][store_id] = mapped_status
            if old_status != mapped_status:
                updated += 1
            matched += 1
            synced.append({
                "skc": skc, "offer_id": offer_id, "product_id": product_id,
                "name": name[:60], "status": mapped_status, "match": "matched"
            })
        else:
            new_skus += 1
            synced.append({
                "skc": "", "offer_id": offer_id, "product_id": product_id,
                "name": name[:60], "status": mapped_status, "match": "new"
            })

    _save_products(products_data)

    # 更新同步状态
    sync_state = _load_sync_state()
    store_sync = sync_state.get(store_id, {})
    now_iso = datetime.now().isoformat()
    store_sync["last_sync"] = now_iso
    store_sync["last_pull_matched"] = matched
    sync_state[store_id] = store_sync
    _save_sync_state(sync_state)

    logger.info("[产品同步] ✅ 完成 | 匹配=%s | 更新=%s | 新SKU=%s",
                matched, updated, new_skus)

    return jsonify({
        "success": True,
        "total_ozon_products": len(all_info_items),
        "matched": matched,
        "new_skus": new_skus,
        "updated": updated,
        "synced_products": synced,
        "last_sync": now_iso,
        "message": f"同步完成：{matched} 个匹配，{updated} 个状态更新，{new_skus} 个新SKU待注册"
    })




# ==================== 物流模板 API ====================

# Logistics 域路由由 DDD 蓝图接管（见上方 register_blueprint）


# ==================== Ozon 上架页面路由 ====================

@app.route("/ozon-listing")
def ozon_listing_page():
    """Ozon 产品上架页面"""
    return render_template("ozon_listing.html")


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
