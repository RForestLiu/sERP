import os
import json
import base64
import shutil
import mimetypes
import uuid
import subprocess
import sys
import io
from datetime import datetime
from PIL import Image

from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv
import requests

load_dotenv()

app = Flask(__name__)

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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
