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
import logging
from datetime import datetime
from PIL import Image

from flask import Flask, request, jsonify, render_template, send_from_directory
import requests

app = Flask(__name__)
logger = logging.getLogger(__name__)

# --------------- 配置 ---------------
API_KEY = os.getenv("API_KEY", "")
API_URL = "https://api.laozhang.ai/v1beta/models/gemini-3.1-flash-image-preview:generateContent"
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TASKS_FILE = os.path.join(DATA_ROOT, "tasks.json")

os.makedirs(DATA_ROOT, exist_ok=True)
if not os.path.exists(TASKS_FILE):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

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

# --------------- API ---------------
@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_tasks()
    return jsonify(tasks)

@app.route("/api/tasks", methods=["POST"])
def create_task():
    tasks = load_tasks()
    # 自动递增任务名称
    existing_names = [t["name"] for t in tasks]
    n = 1
    while f"任务{n}" in existing_names:
        n += 1
    name = f"任务{n}"
    task_id = str(uuid.uuid4())[:8]
    tasks.append({
        "id": task_id,
        "name": name,
        "created_at": datetime.now().isoformat()
    })
    save_tasks(tasks)
    save_task_data(task_id, {"text1": "", "cards": []})
    return jsonify({"id": task_id, "name": name})

@app.route("/api/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    data = load_task_data(task_id)
    tasks = load_tasks()
    task_info = next((t for t in tasks if t["id"] == task_id), None)
    return jsonify({
        "id": task_id,
        "name": task_info["name"] if task_info else "",
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

# 店铺状态枚举
STORE_STATUSES = ["未上架", "待发布", "已上架", "下架回归中"]

def _load_stores():
    """加载店铺列表"""
    if os.path.exists(STORES_FILE):
        try:
            with open(STORES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []

def _next_store_status(current):
    """循环切换店铺状态"""
    if current not in STORE_STATUSES:
        return STORE_STATUSES[0]
    idx = STORE_STATUSES.index(current)
    return STORE_STATUSES[(idx + 1) % len(STORE_STATUSES)]

def _load_products():
    """加载正式产品数据"""
    if os.path.exists(PRODUCTS_FILE):
        try:
            with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"已注册编号": {}, "产品列表": []}

def _save_products(products_data):
    """保存正式产品数据"""
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
        "result": None
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
                "failed": result.get("failed", 0)
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
    """获取采集结果数据"""
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
    
    return jsonify({
        "task_id": task_id,
        "summary": result,
        "product_data": product_data,
        "images_mapping": images_mapping
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
    
    # 从图片分类中提取 SKU 变体
    skus = []
    seen_variants = set()
    for img in images_mapping:
        if img.get("success") and img.get("type") == "sku":
            # 从文件名中提取变体特征
            fname = img.get("new_name", "")
            # 简单处理：每个成功的 sku 图片作为一个变体
            variant = fname.split("_")[-1].replace(".jpg", "").upper() if "_" in fname else f"V{len(skus)+1:02d}"
            if variant not in seen_variants:
                seen_variants.add(variant)
                sku = f"{skc}-{variant}"
                skus.append(sku)
    
    # 如果没有 SKU 变体，至少创建一个默认 SKU
    if not skus:
        skus.append(f"{skc}-DEFAULT")
    
    # 构建正式产品数据
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
        "images_dir": result.get("images_dir", ""),
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


# ==================== 产品管理模块 API ====================

@app.route("/api/products", methods=["GET"])
def get_products():
    """获取所有正式产品列表"""
    products_data = _load_products()
    stores = _load_stores()
    product_list = products_data.get("产品列表", [])
    
    # 为每个产品补充店铺状态（兼容旧数据）
    for p in product_list:
        if "manual_data" not in p:
            p["manual_data"] = {
                "weight_g": "", "size_spec": "", "spec": ""
            }
        else:
            # 迁移旧数据：将旧字段合并到新字段
            md = p["manual_data"]
            # 旧 weight_g 保留，旧 length_cm/width_cm/height_cm 合并到 size_spec
            if md.get("length_cm") or md.get("width_cm") or md.get("height_cm"):
                if not md.get("size_spec"):
                    parts = [md.get("length_cm",""), md.get("width_cm",""), md.get("height_cm","")]
                    if any(parts):
                        md["size_spec"] = "x".join(p for p in parts if p) + "cm"
            # 旧 color/material 合并到 spec
            if md.get("color") or md.get("material"):
                if not md.get("spec"):
                    parts = [md.get("color",""), md.get("material","")]
                    md["spec"] = "/".join(p for p in parts if p)
            # 删除旧字段
            for old_key in ["length_cm", "width_cm", "height_cm", "color", "material"]:
                md.pop(old_key, None)
        if "store_status" not in p:
            p["store_status"] = {}
        for s in stores:
            sid = s["id"]
            if sid not in p["store_status"]:
                p["store_status"][sid] = "未上架"
    
    return jsonify({
        "products": product_list,
        "stores": stores
    })


@app.route("/api/products/<skc>/manual", methods=["PUT"])
def update_product_manual(skc):
    """保存产品的人工登记数据"""
    data = request.get_json()
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    
    for p in product_list:
        if p["skc"] == skc:
            p["manual_data"] = {
                "weight_g": data.get("weight_g", ""),
                "size_spec": data.get("size_spec", ""),
                "spec": data.get("spec", ""),
                "cost_price": data.get("cost_price", ""),
            }
            _save_products(products_data)
            return jsonify({"success": True, "skc": skc})
    
    return jsonify({"error": "产品不存在"}), 404


@app.route("/api/products/<skc>/store_status", methods=["PUT"])
def update_product_store_status(skc):
    """更新产品在某个店铺的状态"""
    data = request.get_json()
    store_id = data.get("store_id")
    new_status = data.get("status")
    
    if not store_id or new_status not in STORE_STATUSES:
        return jsonify({"error": "参数无效"}), 400
    
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    
    for p in product_list:
        if p["skc"] == skc:
            if "store_status" not in p:
                p["store_status"] = {}
            p["store_status"][store_id] = new_status
            _save_products(products_data)
            return jsonify({"success": True, "skc": skc, "store_id": store_id, "status": new_status})
    
    return jsonify({"error": "产品不存在"}), 404


@app.route("/api/products/<skc>/auto_extract", methods=["POST"])
def auto_extract_product(skc):
    """智能识别产品文本中的重量、尺寸、颜色、材质，返回结构化数据"""
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    
    for p in product_list:
        if p["skc"] == skc:
            pd = p.get("product_data", {})
            attrs = pd.get("attributes", {})
            
            # 收集所有文本
            texts = [
                p.get("title", ""),
                pd.get("about_item", ""),
                pd.get("product_description", ""),
                pd.get("description", ""),
                pd.get("title", ""),
            ]
            search_text = " ".join(t for t in texts if t)
            
            result = {}
            
            # === 重量 ===
            weight = attrs.get("weight") or attrs.get("重量") or ""
            if not weight:
                m = re.search(r'(\d+\.?\d*)\s*(?:g|克|gram)', search_text, re.IGNORECASE)
                if m:
                    weight = m.group(1)
            result["weight_g"] = weight
            
            # === 尺寸（长宽高） ===
            size_raw = attrs.get("size") or attrs.get("尺寸") or attrs.get("dimensions") or ""
            length_cm = ""
            width_cm = ""
            height_cm = ""
            
            if not size_raw:
                # 匹配 20×10×3cm / 20x10x3 cm / 20*10*3cm 等
                m = re.search(r'(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*(?:cm|厘米|mm|毫米)?', search_text)
                if m:
                    length_cm, width_cm, height_cm = m.group(1), m.group(2), m.group(3)
                else:
                    # 匹配 尺寸：20×10×3cm 格式
                    m = re.search(r'尺寸[：:]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)', search_text)
                    if m:
                        length_cm, width_cm, height_cm = m.group(1), m.group(2), m.group(3)
            else:
                # 从 size_raw 中解析
                m = re.search(r'(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)', size_raw)
                if m:
                    length_cm, width_cm, height_cm = m.group(1), m.group(2), m.group(3)
            
            result["length_cm"] = length_cm
            result["width_cm"] = width_cm
            result["height_cm"] = height_cm
            
            # === 颜色 ===
            color = attrs.get("color") or attrs.get("颜色") or ""
            if not color:
                # 常见颜色词
                color_keywords = [
                    "black", "white", "red", "blue", "green", "yellow", "pink", "purple",
                    "orange", "brown", "gray", "grey", "gold", "silver", "beige", "cream",
                    "navy", "khaki", "camel", "coffee", "chocolate", "rose", "wine",
                    "黑色", "白色", "红色", "蓝色", "绿色", "黄色", "粉色", "紫色",
                    "橙色", "棕色", "灰色", "金色", "银色", "米色", "卡其", "咖啡",
                    "深棕", "浅棕", "深蓝", "浅蓝", "深灰", "浅灰", "玫瑰", "酒红",
                ]
                found_colors = []
                for c in color_keywords:
                    if c in search_text.lower():
                        found_colors.append(c)
                if found_colors:
                    color = ", ".join(found_colors[:3])
            result["color"] = color
            
            # === 材质 ===
            material = attrs.get("material") or attrs.get("材质") or ""
            if not material:
                material_keywords = [
                    "leather", "genuine leather", "pu leather", "synthetic leather",
                    "fabric", "cotton", "polyester", "nylon", "canvas", "silk",
                    "wool", "linen", "velvet", "suede", "mesh", "rubber",
                    "plastic", "metal", "stainless steel", "alloy", "wood",
                    "皮革", "真皮", "pu皮", "合成革", "布料", "棉", "涤纶",
                    "尼龙", "帆布", "丝绸", "羊毛", "亚麻", "天鹅绒", "麂皮",
                    "橡胶", "塑料", "金属", "不锈钢", "合金", "木质",
                ]
                found_materials = []
                for m in material_keywords:
                    if m in search_text.lower():
                        found_materials.append(m)
                if found_materials:
                    material = ", ".join(found_materials[:3])
            result["material"] = material
            
            return jsonify({"success": True, "skc": skc, "extracted": result})
    
    return jsonify({"error": "产品不存在"}), 404


@app.route("/api/stores", methods=["GET"])
def get_stores():
    """获取所有店铺列表"""
    return jsonify(_load_stores())


@app.route("/api/extract_from_text", methods=["POST"])
def extract_from_text():
    """调用 DeepSeek 从文本中提取重量、尺寸规格、规格，并统一转换为国际单位"""
    data = request.get_json()
    text = (data.get("text", "") or "").strip()
    
    if not text:
        return jsonify({"error": "文本不能为空"}), 400
    
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    
    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "DEEPSEEK_API_KEY not configured"}), 500
    
    system_prompt = """你是一个产品信息提取助手。请从用户提供的产品描述文本中提取三个字段，并**全部转换为国际单位**。

提取规则：
1. weight_g：提取产品的重量，**统一转换为克(g)**。例如 "0.5kg" → "500"，"1.2 pounds" → "544"，"200g" → "200"。只返回数字，不要单位。
2. size_spec：提取产品的尺寸规格，**统一转换为厘米(cm)**，格式为 "长×宽×高cm"。例如 "10x5x2 inches" → "25.4×12.7×5.1cm"，"20×10×3cm" → "20×10×3cm"。如果只有两个维度也按此格式。
3. spec：提取产品的规格描述，如颜色、尺码、型号、款式等变体信息。例如 "黑色/大号"、"红色 S码"。

如果某个字段无法从文本中提取，返回空字符串。

请严格按照以下 JSON 格式返回，不要包含其他内容：
{"weight_g": "", "size_spec": "", "spec": ""}"""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "temperature": 0.1,
        "max_tokens": 256
    }
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            return jsonify({"error": f"DeepSeek API Error {resp.status_code}: {resp.text}"}), 500
        
        result = resp.json()
        response_text = ""
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")
        
        if not response_text:
            return jsonify({"error": "模型未返回文本"}), 500
        
        # 解析 JSON
        import re as re_json
        json_match = re_json.search(r'\{[^{}]*\}', response_text)
        if json_match:
            extracted = json.loads(json_match.group())
        else:
            extracted = {"weight_g": "", "size_spec": "", "spec": ""}
        
        return jsonify({
            "success": True,
            "extracted": {
                "weight_g": extracted.get("weight_g", ""),
                "size_spec": extracted.get("size_spec", ""),
                "spec": extracted.get("spec", "")
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    manual_data = data.get("manual_data", {})
    form_fields = data.get("form_fields", [])

    if not form_fields:
        return jsonify({"error": "表单字段列表不能为空"}), 400

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")

    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "DEEPSEEK_API_KEY not configured"}), 500

    # 构建产品信息摘要
    attrs = product_data.get("attributes", {})
    about_item = product_data.get("about_item", "")
    product_description = product_data.get("product_description", "")
    description = product_data.get("description", "")

    # 收集所有产品文本
    product_texts = [
        product_title,
        about_item,
        product_description,
        description,
    ]
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
        
        field_desc = f"  - 标签: {label or name or '(无标签)'}"
        if placeholder:
            field_desc += f" | 占位: {placeholder}"
        if tag == "select" and options:
            option_texts = [o.get("text", o.get("value", "")) for o in options[:20]]
            field_desc += f" | 选项: {', '.join(option_texts)}"
        fields_summary.append(field_desc)

    fields_text = "\n".join(fields_summary)

    system_prompt = """你是一个电商产品表单自动填充助手。你的任务是根据产品数据，为店小秘 Ozon 产品添加页面的表单字段提供填充值。

## 输入格式
你将收到：
1. 产品信息（标题、描述、属性等）
2. 表单字段列表（每个字段包含标签、占位符、选项等）

## 输出要求
请分析每个表单字段，判断它对应产品数据中的哪个信息，然后给出填充值。

### 字段匹配规则：
- **产品名称/标题** → 匹配标签含"名称""标题""name""title"的字段
- **产品描述** → 匹配标签含"描述""说明""description"的字段
- **价格** → 匹配标签含"价格""售价""price"的字段
- **重量** → 匹配标签含"重量""weight""重さ"的字段
- **尺寸/长宽高** → 匹配标签含"尺寸""长""宽""高""size""dimension"的字段
- **颜色** → 匹配标签含"颜色""color""colour"的字段
- **材质** → 匹配标签含"材质""材料""material"的字段
- **品牌** → 匹配标签含"品牌""brand"的字段
- **分类/品类** → 匹配标签含"分类""品类""category"的字段
- **数量/库存** → 匹配标签含"数量""库存""quantity""stock"的字段
- **对于 select 下拉框**：从选项列表中匹配最接近的值
- **对于 checkbox**：返回 true/false
- **对于其他字段**：根据标签和占位符推断

### 重要规则：
1. 如果某个字段无法匹配到产品数据中的任何信息，返回空字符串
2. 对于下拉框(select)，必须从提供的选项列表中选取值
3. 所有值必须是字符串
4. 不要编造数据，不确定的字段留空

请严格按照以下 JSON 格式返回，不要包含其他内容：
{"mappings": [{"selector": "...", "value": "..."}, ...]}

其中 selector 是表单字段的 CSS 选择器，value 是要填充的值。"""

    user_prompt = f"""## 产品信息
SKC: {skc}
标题: {product_title}

### 产品描述文本
{product_text[:3000]}

### 人工登记数据
{json.dumps(manual_data, ensure_ascii=False, indent=2)}

### 表单字段列表（共 {len(form_fields)} 个字段）
{fields_text}

请分析以上表单字段，为每个字段提供填充值。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4096
    }

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            return jsonify({"error": f"DeepSeek API Error {resp.status_code}: {resp.text}"}), 500

        result = resp.json()
        response_text = ""
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")

        if not response_text:
            return jsonify({"error": "模型未返回文本"}), 500

        # 解析 JSON
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            mappings = parsed.get("mappings", [])
        else:
            mappings = []

        # 验证 mappings 格式
        validated_mappings = []
        for m in mappings:
            if isinstance(m, dict) and "selector" in m:
                validated_mappings.append({
                    "selector": m.get("selector", ""),
                    "value": m.get("value", "")
                })

        return jsonify({
            "success": True,
            "skc": skc,
            "mappings": validated_mappings,
            "total_fields": len(form_fields),
            "filled_fields": len(validated_mappings)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 店铺凭证管理 API ====================

@app.route("/api/stores/<store_id>", methods=["GET"])
def get_store(store_id):
    """获取单个店铺详情（含 Ozon 凭证）"""
    stores = _load_stores()
    store = next((s for s in stores if s["id"] == store_id), None)
    if not store:
        return jsonify({"error": "店铺不存在"}), 404
    return jsonify(store)


@app.route("/api/stores/<store_id>", methods=["PUT"])
def update_store(store_id):
    """更新店铺信息（含 Ozon 凭证）"""
    data = request.get_json()
    stores = _load_stores()
    store = next((s for s in stores if s["id"] == store_id), None)
    if not store:
        return jsonify({"error": "店铺不存在"}), 404
    
    # 更新允许的字段
    for key in ["client_id", "api_key", "label", "name"]:

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


# Ozon 缓存目录
OZON_CACHE_DIR = os.path.join(DATA_ROOT, "ozon_cache")
os.makedirs(OZON_CACHE_DIR, exist_ok=True)

def _get_cached_category_tree(store_id, refresh=False):
    """获取品类树（优先从缓存读取）"""
    cache_path = os.path.join(OZON_CACHE_DIR, f"{store_id}_category_tree.json")
    
    # 如果不需要刷新且缓存存在，从缓存读取
    if not refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                tree = json.load(f)
            # 统计树中节点数
            def count_nodes(nodes):
                cnt = 0
                for n in nodes:
                    cnt += 1
                    children = n.get("children", [])
                    if children:
                        cnt += count_nodes(children)
                return cnt
            node_count = count_nodes(tree)
            logger.info("[品类] 从缓存读取品类树成功 | store=%s | 节点数≈%s+ | 文件=%s", store_id, node_count, cache_path)
            return tree, None
        except Exception as e:
            logger.warning("[品类] 缓存文件读取失败: %s，将重新从 API 拉取", e)
    
    # 从 Ozon API 获取
    logger.info("[品类] 从 Ozon API 拉取品类树 | store=%s", store_id)
    result, err = _call_ozon_api(store_id, "/v1/description-category/tree")
    if err:
        logger.error("[品类] API 拉取品类树失败: %s", err)
        return None, err
    
    tree = result.get("result", [])
    if not tree:
        logger.error("[品类] API 返回的品类树为空")
        return None, "品类树为空"
    
    # 保存到缓存
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, indent=2, ensure_ascii=False)
        logger.info("[品类] 品类树已保存到缓存 | 文件=%s", cache_path)
    except Exception as e:
        logger.warning("[品类] 保存缓存失败: %s", e)
    
    return tree, None


def _load_or_create_translations(store_id):
    """加载或创建品类翻译缓存"""
    trans_path = os.path.join(OZON_CACHE_DIR, f"{store_id}_translations.json")
    if os.path.exists(trans_path):
        try:
            with open(trans_path, "r", encoding="utf-8") as f:
                return json.load(f), trans_path
        except:
            pass
    return {}, trans_path


def _save_translations(trans_path, translations):
    """保存翻译缓存"""
    try:
        with open(trans_path, "w", encoding="utf-8") as f:
            json.dump(translations, f, indent=2, ensure_ascii=False)
    except:
        pass


def _batch_translate_categories(translations, untranslated, trans_path, store_id, batch_label="品类"):
    """
    通用批量翻译函数：调用 DeepSeek 翻译一批品类名，自动保存缓存
    
    参数:
        translations: dict[str, str] — 翻译缓存（会被直接修改，追加翻译结果）
        untranslated: list[dict] — 待翻译品类 [{id, name, path}, ...]
        trans_path: str — 缓存文件路径
        store_id: str — 店铺 ID（仅用于日志）
        batch_label: str — 日志标签（如 "大类: Товары для животных"）
    
    返回:
        (translated_count, error_count)
    """
    if not untranslated:
        return 0, 0
    
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    
    if not DEEPSEEK_API_KEY:
        logger.warning("[%s] ⚠️ 未配置 DEEPSEEK_API_KEY，跳过翻译", batch_label)
        return 0, len(untranslated)
    
    need_translate = len(untranslated)
    logger.info("[%s] 🚀 发送 %s 个品类给 DeepSeek 翻译...", batch_label, need_translate)
    
    cat_lines = "\n".join([
        f"{j+1}. [{c['id']}] {c['path']}"
        for j, c in enumerate(untranslated)
    ])
    
    trans_prompt = f"""你是一个电商翻译助手。请将以下 Ozon 电商平台的俄语品类名称翻译成中文。

每个品类包含路径信息（"俄语>俄语"格式），你只需要翻译品类名本身。

翻译要求：
- 准确传达原意
- 使用电商行业通用术语
- 对于品牌词、专有名词保留原文

请严格按照以下 JSON 格式返回翻译结果，不要包含其他内容：
{{"translations": [
  {{"id": 123, "name_cn": "中文翻译"}},
  ...
]}}

需要翻译的品类列表：
{cat_lines}"""
    
    translated_count = 0
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }, json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": trans_prompt}],
            "temperature": 0.1,
            "max_tokens": 32768
        }, timeout=300)
        
        if resp.status_code == 200:
            llm_result = resp.json()
            choices = llm_result.get("choices", [])
            if choices:
                llm_text = choices[0].get("message", {}).get("content", "")
                logger.info("[%s] DeepSeek 返回长度: %s 字符", batch_label, len(llm_text))
                json_match = re.search(r'\{[^{}]*\}', llm_text, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group())
                        for t in parsed.get("translations", []):
                            tid = str(t.get("id"))
                            name_cn = t.get("name_cn", "")
                            if name_cn:
                                translations[tid] = name_cn
                                translated_count += 1
                        logger.info("[%s] ✅ 成功解析 %s 个翻译结果", batch_label, translated_count)
                    except Exception as e:
                        logger.error("[%s] ❌ JSON 解析错误: %s", batch_label, e)
                else:
                    logger.warning("[%s] ❌ DeepSeek 返回中未找到 JSON", batch_label)
                    logger.warning("[%s] 返回内容前 200 字: %s", batch_label, llm_text[:200])
        else:
            logger.warning("[%s] ⚠️ DeepSeek API 调用失败: HTTP %s", batch_label, resp.status_code)
            logger.warning("[%s] 响应内容: %s", batch_label, resp.text[:300])
    except Exception as e:
        logger.error("[%s] ❌ 翻译请求异常: %s", batch_label, e)
    
    # 每翻译完一批立即保存缓存
    _save_translations(trans_path, translations)
    
    error_count = need_translate - translated_count
    return translated_count, error_count


@app.route("/api/ozon/<store_id>/category-tree", methods=["GET"])
def ozon_category_tree(store_id):
    """获取 Ozon 全品类树（带缓存）"""
    refresh = request.args.get("refresh", "0") == "1"
    
    tree, err = _get_cached_category_tree(store_id, refresh=refresh)
    if err:
        return jsonify({"error": err}), 500
    
    return jsonify({
        "success": True,
        "category_tree": tree
    })


@app.route("/api/ozon/<store_id>/translate-categories", methods=["POST"])
def ozon_translate_categories(store_id):
    """
    批量翻译品类名（俄语→中文），带缓存
    输入：{"categories": [{"id": 123, "name": "俄语名", "path": "父级>子级"}, ...]}
    输出：{"translations": [{"id": 123, "name_ru": "...", "name_cn": "..."}, ...]}
    """
    import time
    t_start = time.time()
    data = request.get_json()
    categories = data.get("categories", [])
    
    total_requested = len(categories)
    logger.info("[品类翻译] 收到翻译请求 | store=%s | 请求翻译 %s 个品类", store_id, total_requested)
    
    if not categories:
        return jsonify({"error": "categories 不能为空"}), 400
    
    # 加载已有翻译缓存
    translations, trans_path = _load_or_create_translations(store_id)
    cached_count = len(translations)
    
    # 找出需要翻译的品类（未在缓存中的）
    untranslated = []
    for c in categories:
        cid = str(c.get("id"))
        if cid not in translations:
            untranslated.append(c)
    
    logger.info("[品类翻译] 缓存已有 %s 个翻译 | 需要新翻译: %s/%s", cached_count, len(untranslated), total_requested)
    
    # 复用公共翻译函数
    if untranslated:
        trans_count, err_count = _batch_translate_categories(
            translations, untranslated, trans_path, store_id,
            batch_label="品类翻译"
        )
        logger.info("[品类翻译] 翻译完成 | 成功: %s | 失败: %s", trans_count, err_count)
    
    # 构建返回结果
    result = []
    for c in categories:
        cid = str(c.get("id"))
        name_cn = translations.get(cid, "")
        result.append({
            "id": c.get("id"),
            "name_ru": c.get("name", ""),
            "name_cn": name_cn,
            "path": c.get("path", "")
        })
    
    return jsonify({
        "success": True,
        "translations": result,
        "translated_count": len([r for r in result if r["name_cn"]]),
        "total_categories": len(categories)
    })


# ==================== 品类树刷新异步进度追踪 ====================
# 用于在后台线程中分批翻译品类，前端轮询进度

# 品类树刷新任务状态（按 store_id 索引）
_refresh_tasks = {}  # {store_id: {status, progress, message, total_batches, current_batch, ...}}

def _run_refresh_in_background(store_id):
    """在后台线程中执行品类树刷新+分批翻译"""
    import time
    t_start = time.time()
    
    # 初始化进度
    _refresh_tasks[store_id] = {
        "status": "running",
        "progress": 0,
        "message": "拉取品类树...",
        "total_groups": 0,
        "current_group": 0,
        "total_nodes": 0,
        "translated": 0,
        "need_translate": 0,
        "error": None
    }
    
    try:
        logger.info("=" * 50)
        logger.info("[品类刷新][后台] 开始刷新品类树 | store=%s", store_id)
        logger.info("=" * 50)
        
        # 1. 强制刷新品类树
        _refresh_tasks[store_id]["message"] = "正在从 Ozon API 拉取品类树..."
        tree, err = _get_cached_category_tree(store_id, refresh=True)
        if err:
            _refresh_tasks[store_id]["status"] = "error"
            _refresh_tasks[store_id]["error"] = f"获取品类树失败: {err}"
            return
        if not tree:
            _refresh_tasks[store_id]["status"] = "error"
            _refresh_tasks[store_id]["error"] = "品类树为空"
            return
        
        # 2. 展平所有节点
        _refresh_tasks[store_id]["message"] = "展平品类树..."
        def _node_id(node):
            return node.get("type_id") or node.get("description_category_id") or node.get("id")
        def _node_name(node):
            return node.get("type_name") or node.get("category_name") or node.get("name", "")
        
        all_nodes = []
        def flatten_all(nodes, path="", root_type_id=None, root_name=""):
            for node in nodes:
                node_id = _node_id(node)
                node_name = _node_name(node)
                current_path = f"{path} > {node_name}" if path else node_name
                current_root_id = root_type_id or node_id
                current_root_name = root_name or node_name
                if node_id:
                    all_nodes.append({
                        "id": node_id,
                        "name": node_name,
                        "path": current_path,
                        "type_id": current_root_id,
                        "type_name": current_root_name
                    })
                children = node.get("children", [])
                if children:
                    flatten_all(children, current_path, current_root_id, current_root_name)
        
        flatten_all(tree)
        total_count = len(all_nodes)
        _refresh_tasks[store_id]["total_nodes"] = total_count
        
        # 3. 按 type_id 分组，逐批翻译
        translations, trans_path = _load_or_create_translations(store_id)
        untranslated = [n for n in all_nodes if str(n["id"]) not in translations]
        need_translate = len(untranslated)
        cache_hit = total_count - need_translate
        _refresh_tasks[store_id]["need_translate"] = need_translate
        
        if need_translate > 0:
            # 按 type_id 分组
            groups = {}
            group_names = {}
            for n in untranslated:
                tid = n.get("type_id", "unknown")
                if tid not in groups:
                    groups[tid] = []
                    group_names[tid] = n.get("type_name", f"大类_{tid}")
                groups[tid].append(n)
            
            type_ids_sorted = sorted(groups.keys(), key=lambda x: str(x))
            total_groups = len(type_ids_sorted)
            _refresh_tasks[store_id]["total_groups"] = total_groups
            _refresh_tasks[store_id]["message"] = f"开始翻译 0/{total_groups} 个大类..."
            
            translated_count = 0
            batch_index = 0
            for tid in type_ids_sorted:
                batch = groups[tid]
                batch_index += 1
                type_name = group_names[tid]
                batch_label = f"品类刷新 第{batch_index}/{total_groups}批({type_name})"
                
                # 更新进度
                _refresh_tasks[store_id].update({
                    "current_group": batch_index,
                    "message": f"正在翻译 {batch_index}/{total_groups} 个大类（{type_name}，共 {len(batch)} 个品类）..."
                })
                
                logger.info("[品类刷新][后台] --- 第 %s/%s 批：%s（%s 个品类）---", batch_index, total_groups, type_name, len(batch))
                trans_count, err_count = _batch_translate_categories(
                    translations, batch, trans_path, store_id,
                    batch_label=batch_label
                )
                translated_count += trans_count
                
                # 更新进度
                progress_pct = int(batch_index / total_groups * 100)
                _refresh_tasks[store_id].update({
                    "progress": progress_pct,
                    "translated": translated_count,
                    "message": f"已翻译 {batch_index}/{total_groups} 个大类（{translated_count}/{need_translate} 个品类）"
                })
        else:
            _refresh_tasks[store_id]["message"] = "所有品类已有翻译缓存，无需翻译"
        
        # 4. 读取最终翻译缓存并构建返回数据
        translations, _ = _load_or_create_translations(store_id)
        enriched_tree = _enrich_tree_with_translations(tree, translations)
        
        elapsed = time.time() - t_start
        _refresh_tasks[store_id].update({
            "status": "completed",
            "progress": 100,
            "message": f"品类树已更新，共 {total_count} 个品类",
            "result_tree": enriched_tree
        })
        logger.info("[品类刷新][后台] ✅ 完成 | 总耗时 %.1fs", elapsed)
    except Exception as e:
        _refresh_tasks[store_id].update({
            "status": "error",
            "error": str(e),
            "message": f"刷新失败: {str(e)}"
        })
        logger.error("[品类刷新][后台] ❌ 异常: %s", e)


@app.route("/api/ozon/<store_id>/refresh-categories", methods=["POST"])
def ozon_refresh_categories(store_id):
    """
    一键刷新品类树 + 批量翻译所有品类名（俄→中）
    改为后台异步执行，返回立即响应，前端通过轮询获取进度
    """
    import threading
    
    # 检查是否已有运行中的任务
    if store_id in _refresh_tasks and _refresh_tasks[store_id]["status"] == "running":
        return jsonify({
            "success": True,
            "async": True,
            "message": "品类树正在刷新中，请稍候..."
        })
    
    # 启动后台线程
    thread = threading.Thread(target=_run_refresh_in_background, args=(store_id,), daemon=True)
    thread.start()
    
    return jsonify({
        "success": True,
        "async": True,
        "message": "品类树刷新任务已启动"
    })


@app.route("/api/ozon/<store_id>/refresh-categories/status", methods=["GET"])
def ozon_refresh_categories_status(store_id):
    """查询品类树刷新任务进度"""
    task = _refresh_tasks.get(store_id)
    
    if not task:
        return jsonify({
            "exists": False,
            "status": "idle",
            "progress": 0,
            "message": "尚未执行过品类树刷新"
        })
    
    return jsonify({
        "exists": True,
        "status": task["status"],
        "progress": task["progress"],
        "message": task["message"],
        "total_groups": task.get("total_groups", 0),
        "current_group": task.get("current_group", 0),
        "total_nodes": task.get("total_nodes", 0),
        "translated": task.get("translated", 0),
        "need_translate": task.get("need_translate", 0),
        "error": task.get("error"),
        "has_result": task.get("status") == "completed" and task.get("result_tree") is not None
    })


def _enrich_tree_with_translations(nodes, translations):
    """递归为品类树节点附加中文翻译"""
    result = []
    for node in nodes:
        node_id = node.get("type_id") or node.get("description_category_id") or node.get("id")
        node_name = node.get("type_name") or node.get("category_name") or node.get("name", "")
        cn = translations.get(str(node_id), "")
        enriched = dict(node)  # 复制原节点
        enriched["_name_cn"] = cn
        children = node.get("children", [])
        if children:
            enriched["children"] = _enrich_tree_with_translations(children, translations)
        result.append(enriched)
    return result


@app.route("/api/ozon/<store_id>/match-category", methods=["POST"])
def ozon_match_category(store_id):
    """
    根据产品信息自动匹配最合适的 Ozon 品类
    输入：product_title, product_category (如"钱包"), product_description
    流程：获取品类树（含中文翻译）→ 展平为紧凑格式 → DeepSeek 直接匹配 → 返回品类
    """
    import time
    t_start = time.time()
    data = request.get_json()
    product_title = data.get("product_title", "")
    product_category = data.get("product_category", "")
    product_description = data.get("product_description", "")
    
    logger.info("=" * 50)
    logger.info("[品类匹配] 开始自动匹配品类 | store=%s", store_id)
    logger.info("[品类匹配] 产品标题: %s", product_title[:80])
    logger.info("[品类匹配] 产品品类: %s", product_category)
    logger.info("=" * 50)
    
    if not product_title and not product_category:
        logger.warning("[品类匹配] ❌ 产品标题和品类均为空")
        return jsonify({"error": "请提供产品标题或品类名称"}), 400
    
    # 1. 获取品类树（使用缓存）
    logger.info("[品类匹配] 第 1 步：获取品类树...")
    tree, err = _get_cached_category_tree(store_id)
    if err:
        logger.error("[品类匹配] ❌ 获取品类树失败: %s", err)
        return jsonify({"error": f"获取品类树失败: {err}"}), 500
    if not tree:
        logger.error("[品类匹配] ❌ 品类树为空")
        return jsonify({"error": "品类树为空"}), 500
    logger.info("[品类匹配] ✅ 品类树获取成功")
    
    # 2. 加载翻译缓存
    translations, _ = _load_or_create_translations(store_id)
    trans_count = len(translations)
    logger.info("[品类匹配] 翻译缓存: %s 个品类已翻译", trans_count)
    
    # 3. 展平品类树为紧凑格式（含中文翻译）
    logger.info("[品类匹配] 第 2 步：展平品类树为文本格式...")
    def _node_id(node):
        return node.get("type_id") or node.get("description_category_id") or node.get("id")
    
    def _node_name(node):
        return node.get("type_name") or node.get("category_name") or node.get("name", "")
    
    # 构建树的文本表示（带缩进，含俄文名+中文翻译）
    tree_lines = []
    def format_tree(nodes, depth=0):
        for node in nodes:
            node_id = _node_id(node)
            node_name = _node_name(node)
            node_cn = translations.get(str(node_id), "")
            indent = "  " * depth
            # 格式: ─ [ID] 俄语名（中文名）
            display = node_name
            if node_cn and node_cn != node_name:
                display = f"{node_name}（{node_cn}）"
            tree_lines.append(f"{indent}─ [{node_id}] {display}")
            children = node.get("children", [])
            if children:
                format_tree(children, depth + 1)
    
    format_tree(tree)
    tree_text = "\n".join(tree_lines)
    total_nodes = len(tree_lines)
    logger.info("[品类匹配] 品类树文本: %s 行, %s 字符", total_nodes, len(tree_text))
    logger.info("[品类匹配] 估算 Token: ~%s", len(tree_text) // 2 + total_nodes * 5)
    logger.info("[品类匹配] ✅ 全量发送（共 %s 个品类）", total_nodes)
    
    # 4. 调用 DeepSeek 直接匹配
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
    
    best_match = None
    
    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "DEEPSEEK_API_KEY not configured"}), 500
    
    system_prompt = """你是一个 Ozon 电商品类匹配专家。你的任务是从给定的 Ozon 品类树中，为产品选择最合适的品类。

## 输入
- 产品信息（标题、品类、描述）
- Ozon 品类树（用缩进表示层级，格式：─ [品类ID] 俄语名（中文名））

## 输出要求
请分析产品信息，从品类树中选出 **1 个** 最匹配的**叶子品类**（即没有子品类的具体品类）。
如果找不到合适的品类，返回 null。

### 评分标准：
1. 品类名称和产品标题/描述在语义上匹配（注意品类名是俄语+中文对照，产品信息是中文/英文）
2. 品类在树中的层级越深（越具体）越好
3. 宁可匹配一个大致相关的品类，也不要返回 null
4. **品类 ID 必须从上方品类树中选取，不要自己编造品类 ID**

请严格按照以下 JSON 格式返回，不要包含其他内容：
{"category_id": 12345, "reason": "匹配理由（简要说明中文）"} 
或
{"category_id": null, "reason": "无法匹配合适的品类的原因"}"""

    user_prompt = f"""## 产品信息
标题: {product_title or "未提供"}
品类: {product_category or "未提供"}
描述: {product_description[:500] if product_description else "未提供"}

## Ozon 品类树（共 {total_nodes} 个品类，品类 ID 必须从下方列表中选取）
{tree_text}

请从以上品类树中选出最匹配的一个品类，返回其 ID 和匹配理由。"""

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }, json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 512
        }, timeout=60)
        
        if resp.status_code == 200:
            llm_result = resp.json()
            llm_text = ""
            choices = llm_result.get("choices", [])
            if choices:
                llm_text = choices[0].get("message", {}).get("content", "")
            
            if llm_text:
                logger.debug("[品类匹配] DeepSeek原始响应: %s", llm_text[:500])
                json_match = re.search(r'\{[^{}]*\}', llm_text, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group())
                        category_id = parsed.get("category_id")
                        reason = parsed.get("reason", "")
                        logger.debug("[品类匹配] 解析结果: category_id=%s, reason=%s", category_id, reason)
                        
                        if category_id is not None:
                            # 从树中查找对应的品类信息
                            def find_in_tree(nodes, target_id):
                                for node in nodes:
                                    node_id = _node_id(node)
                                    if str(node_id) == str(target_id):
                                        return node
                                    children = node.get("children", [])
                                    if children:
                                        found = find_in_tree(children, target_id)
                                        if found:
                                            return found
                                return None
                            
                            found_node = find_in_tree(tree, category_id)
                            if found_node:
                                # 构建路径
                                best_match = {
                                    "id": _node_id(found_node),
                                    "name": _node_name(found_node),
                                    "path": "",  # 前端可以自己构建路径
                                    "reason": reason
                                }
                                logger.debug("[品类匹配] 找到匹配: %s", _node_name(found_node))
                            else:
                                logger.warning("[品类匹配] 品类ID %s 在树中未找到", category_id)
                    except Exception as e:
                        logger.warning("[品类匹配] JSON解析错误: %s", e)
                else:
                    logger.warning("[品类匹配] 返回中未找到JSON")
            else:
                logger.warning("[品类匹配] DeepSeek返回为空")
        else:
            logger.warning("[品类匹配] DeepSeek API错误: %s %s", resp.status_code, resp.text[:500])
    except Exception as e:
        logger.error("[品类匹配] DeepSeek匹配异常: %s", e)
    
    return jsonify({
        "success": True,
        "best_match": best_match,
        "total_categories": total_nodes
    })


@app.route("/api/ozon/<store_id>/category-attributes", methods=["POST"])
def ozon_category_attributes(store_id):
    """获取 Ozon 品类属性列表（增加了根节点友好提示）"""
    data = request.get_json()
    category_id = data.get("description_category_id", 0)
    
    logger.info("[品类属性] 获取品类属性 | store=%s | category_id=%s", store_id, category_id)
    
    if not category_id:
        logger.warning("[品类属性] ❌ category_id 为空")
        return jsonify({"error": "请提供 description_category_id"}), 400
    
    # 获取品类属性
    result, err = _call_ozon_api(store_id, "/v1/description-category/attribute", {
        "description_category_id": category_id
    })
    
    if err:
        logger.error("[品类属性] ❌ API 调用失败: %s", err)
        # 如果是 Ozon API 错误，检查是否是品类太宽泛的问题
        if "Error 400" in err or "Error 404" in err or "not found" in err.lower():
            logger.warning("[品类属性] 💡 可能是根节点品类，返回空属性")
            return jsonify({
                "success": True,
                "description_category_id": category_id,
                "attributes": [],
                "is_leaf": False,
                "warning": f"当前品类（ID: {category_id}）可能是根节点或父级品类，没有可配置的产品属性。请选择一个更具体的子品类。"
            })
        return jsonify({"error": err}), 500
    
    # 获取每个属性的字典值
    attributes = result.get("result", [])
    logger.info("[品类属性] ✅ API 返回 %s 个属性", len(attributes))
    
    enriched = []
    for attr in attributes:
        attr_id = attr.get("id")
        attr_name = attr.get("name")
        attr_type = attr.get("type")
        
        enriched_attr = {
            "id": attr_id,
            "name": attr_name,
            "description": attr.get("description", ""),
            "type": attr_type,
            "is_required": attr.get("is_required", False),
            "is_collection": attr.get("is_collection", False),
            "max_value_count": attr.get("max_value_count", 1),
            "dictionary_values": []
        }
        
        # 如果是字典类型，获取可选值
        if attr_type == "dictionary":
            try:
                values_result, values_err = _call_ozon_api(store_id, "/v1/description-category/attribute/values", {
                    "attribute_id": attr_id,
                    "description_category_id": category_id
                })
                if not values_err and values_result:
                    dict_values = values_result.get("result", [])
                    enriched_attr["dictionary_values"] = dict_values
                    logger.info("[品类属性]   属性 '%s'(ID=%s) 加载了 %s 个可选值", attr_name, attr_id, len(dict_values))
                else:
                    logger.warning("[品类属性]   属性 '%s'(ID=%s) 加载可选值失败: %s", attr_name, attr_id, values_err)
            except Exception as e:
                logger.error("[品类属性]   属性 '%s'(ID=%s) 加载可选值异常: %s", attr_name, attr_id, e)
        
        enriched.append(enriched_attr)
    
    is_leaf = len(enriched) > 0
    logger.info("[品类属性] ✅ 最终返回 %s 个属性, is_leaf=%s", len(enriched), is_leaf)
    
    return jsonify({
        "success": True,
        "description_category_id": category_id,
        "attributes": enriched,
        "is_leaf": is_leaf,
        "warning": "" if is_leaf else f"当前品类（ID: {category_id}）没有可配置的产品属性，请尝试选择一个更具体的子品类。"
    })


@app.route("/api/auto-fill/ozon-fields", methods=["POST"])
def auto_fill_ozon_fields():
    """
    接收产品数据 + Ozon 品类属性列表，
    调用 DeepSeek 分析并返回每个属性字段的填充建议。
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

    # 构建产品信息摘要
    about_item = product_data.get("about_item", "")
    product_description = product_data.get("product_description", "")
    description = product_data.get("description", "")
    product_texts = [product_title, about_item, product_description, description]
    product_text = "\n".join(t for t in product_texts if t)

    # 构建 Ozon 属性摘要
    attrs_summary = []
    for attr in ozon_attributes:
        desc = f"  - ID:{attr.get('id')} 名称:{attr.get('name')} 类型:{attr.get('type')} 必填:{attr.get('is_required')}"
        if attr.get("dictionary_values"):
            vals = [v.get("value", "") for v in attr["dictionary_values"][:30]]
            desc += f" 可选值: {', '.join(vals)}"
        attrs_summary.append(desc)
    
    attrs_text = "\n".join(attrs_summary)

    system_prompt = """你是一个 Ozon 商品上架助手。你的任务是根据产品数据，为 Ozon 品类属性字段提供填充值。

## 输入格式
你将收到：
1. 产品信息（标题、描述、属性等）
2. Ozon 品类属性列表（每个属性包含 ID、名称、类型、可选值等）

## 输出要求
请分析每个 Ozon 属性，判断它对应产品数据中的哪个信息，然后给出填充值。

### 字段匹配规则：
- **产品名称/标题** → 匹配名称含"名称""标题""name""title"的属性
- **产品描述** → 匹配名称含"描述""说明""description"的属性
- **品牌** → 匹配名称含"品牌""brand"的属性
- **颜色** → 匹配名称含"颜色""color""colour"的属性
- **材质** → 匹配名称含"材质""材料""material"的属性
- **重量** → 匹配名称含"重量""weight"的属性
- **尺寸/长宽高** → 匹配名称含"尺寸""长""宽""高""size""dimension"的属性
- **性别** → 匹配名称含"性别""sex""gender"的属性
- **年龄** → 匹配名称含"年龄""age"的属性
- **原产国** → 匹配名称含"国家""country""原产"的属性

### 重要规则：
1. 对于 dictionary 类型的属性，必须从提供的可选值列表中选取
2. 如果某个属性无法匹配到产品数据中的任何信息，value 返回空字符串
3. 所有值必须是字符串
4. 不要编造数据，不确定的字段留空

请严格按照以下 JSON 格式返回，不要包含其他内容：
{"mappings": [{"attribute_id": 123, "value": "填充值"}, ...]}

其中 attribute_id 是 Ozon 属性的 ID，value 是要填充的值。"""

    user_prompt = f"""## 产品信息
SKC: {skc}
标题: {product_title}

### 产品描述文本
{product_text[:3000]}

### 人工登记数据
{json.dumps(manual_data, ensure_ascii=False, indent=2)}

### Ozon 品类属性列表（共 {len(ozon_attributes)} 个属性）
{attrs_text}

请分析以上 Ozon 属性，为每个属性提供填充值。"""

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4096
    }

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            return jsonify({"error": f"DeepSeek API Error {resp.status_code}: {resp.text}"}), 500

        result = resp.json()
        response_text = ""
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")

        if not response_text:
            return jsonify({"error": "模型未返回文本"}), 500

        # 解析 JSON
        json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            mappings = parsed.get("mappings", [])
        else:
            mappings = []

        # 验证 mappings 格式
        validated_mappings = []
        for m in mappings:
            if isinstance(m, dict) and "attribute_id" in m:
                validated_mappings.append({
                    "attribute_id": m.get("attribute_id"),
                    "value": m.get("value", "")
                })

        return jsonify({
            "success": True,
            "skc": skc,
            "mappings": validated_mappings,
            "total_attributes": len(ozon_attributes),
            "filled_attributes": len(validated_mappings)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 产品图片 API ====================

@app.route("/api/products/<skc>/images", methods=["GET"])
def get_product_images(skc):
    """获取产品的正式图片列表"""
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    
    for p in product_list:
        if p["skc"] == skc:
            images = []
            
            # 1. 从 product_data.image_urls 获取
            pd = p.get("product_data", {})
            image_urls = pd.get("image_urls", [])
            for url in image_urls:
                images.append({
                    "source": "url",
                    "url": url,
                    "order": len(images)
                })
            
            # 2. 从 images_dir 获取本地图片
            images_dir = p.get("images_dir", "")
            if images_dir and os.path.exists(images_dir):
                for fname in sorted(os.listdir(images_dir)):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp'):
                        # 检查是否已存在（避免重复）
                        if not any(img.get("local_path", "").endswith(fname) for img in images):
                            images.append({
                                "source": "local",
                                "local_path": os.path.join(images_dir, fname),
                                "url": f"/product_images/{skc}/{fname}",
                                "order": len(images)
                            })
            
            return jsonify({
                "success": True,
                "skc": skc,
                "images": images
            })
    
    return jsonify({"error": "产品不存在"}), 404


@app.route("/product_images/<skc>/<path:filename>")
def serve_product_image(skc, filename):
    """提供产品图片的静态文件服务"""
    products_data = _load_products()
    product_list = products_data.get("产品列表", [])
    for p in product_list:
        if p["skc"] == skc:
            images_dir = p.get("images_dir", "")
            if images_dir and os.path.exists(images_dir):
                return send_from_directory(images_dir, filename)
    return "", 404


# ==================== Ozon 上架页面路由 ====================

@app.route("/ozon-listing")
def ozon_listing_page():
    """Ozon 产品上架页面"""
    return render_template("ozon_listing.html")


# 应用实例导入：从 main.py 启动应用
# if __name__ == "__main__":
#     app.run(debug=True, port=5000)
