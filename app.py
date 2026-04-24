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

if __name__ == "__main__":
    app.run(debug=True, port=5000)