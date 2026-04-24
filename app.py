import os
import re
import uuid
import base64
import requests
import json
import logging
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

# ── 日志配置 ─────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "sERP.log"
# 只记录我们自己的日志，过滤第三方库
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, stream_handler]
)

# 降低第三方库日志级别
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── 初始化 ─────────────────────────────────────────────────────
load_dotenv(override=True)

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
TASKS_DIR = Path("tasks")  # 任务数据存储目录
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
TASKS_DIR.mkdir(exist_ok=True)


def _sanitize_base_url(url: str) -> str:
    """确保 base_url 只保留到 /v1，去掉多余端点路径"""
    url = re.sub(r'(/v1).*$', r'\1', url.rstrip("/"))
    return url


_base_url = _sanitize_base_url(
    os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
)

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=_base_url,
)


# ── 任务持久化工具函数 ───────────────────────────────────────────
def get_task_filepath(task_id: str) -> Path:
    """获取任务JSON文件路径"""
    return TASKS_DIR / f"{task_id}.json"


def load_task(task_id: str) -> dict | None:
    """从文件加载任务"""
    filepath = get_task_filepath(task_id)
    if not filepath.exists():
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def save_task(task: dict) -> bool:
    """保存任务到文件"""
    task_id = task.get('id')
    if not task_id:
        return False
    filepath = get_task_filepath(task_id)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(task, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存任务失败: {e}")
        return False


def delete_task_file(task_id: str) -> bool:
    """删除任务文件"""
    filepath = get_task_filepath(task_id)
    try:
        if filepath.exists():
            filepath.unlink()
        return True
    except Exception:
        return False


def list_all_tasks() -> list[dict]:
    """获取所有任务列表"""
    tasks = []
    for filepath in TASKS_DIR.glob("*.json"):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                task = json.load(f)
                tasks.append(task)
        except Exception:
            continue
    # 按创建时间排序（最新在前）
    tasks.sort(key=lambda t: t.get('created_at', ''), reverse=True)
    return tasks


# ── 工具函数 ───────────────────────────────────────────────────
import mimetypes

CODE_VERSION = "v0.4.0"

# ── API 调用封装 ───────────────────────────────────────────────────

def call_gemini_api(image_path: str | None, prompt: str) -> str:
    """
    调用 Gemini 生图 API，返回 base64 数据。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.laozhang.ai").rstrip("/")
    
    url = f"{base_url}/v1beta/models/{model}:generateContent"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    parts = [{"text": prompt}]
    
    # 如果有参考图片，编码为 inline_data
    if image_path and Path(image_path).exists():
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        parts.append({"inline_data": {"mime_type": mime_type, "data": image_b64}})
        logger.info(f"[Gemini] 已添加参考图片: {image_path}")
    
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"imageSize": "2K"}
        }
    }
    
    logger.info(f"[Gemini] 请求URL: {url}")
    response = requests.post(url, headers=headers, json=payload, timeout=180)
    
    if response.status_code != 200:
        raise ValueError(f"Gemini API 错误 {response.status_code}: {response.text}")
    
    result = response.json()
    
    # 从 Gemini 响应中提取图片
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                logger.info(f"[Gemini] 返回 base64 数据")
                return inline_data["data"]
    
    raise ValueError(f"Gemini API 返回结果中无图片数据: {result}")


def call_openai_api(image_path: str | None, prompt: str) -> str:
    """
    调用 OpenAI 格式生图 API，返回 URL 或 base64 数据。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.laozhang.ai/v1").rstrip("/")
    model = os.getenv("IMAGE_MODEL", "gpt-image-2")
    size = os.getenv("IMAGE_SIZE", "1024x1024")
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # 有参考图 → edit，无图 → generate
    if image_path and Path(image_path).exists():
        url = f"{base_url}/images/edits"
        data = {"model": model, "prompt": prompt, "n": 1, "size": size}
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        
        with open(image_path, "rb") as f:
            files = [("image", (Path(image_path).name, f, mime_type))]
            response = requests.post(url, headers=headers, data=data, files=files, timeout=300)
        logger.info(f"[OpenAI] 图片编辑模式: {url}")
    else:
        url = f"{base_url}/images/generations"
        data = {"model": model, "prompt": prompt, "n": 1, "size": size}
        response = requests.post(url, headers=headers, json=data, timeout=300)
        logger.info(f"[OpenAI] 纯文本生成模式: {url}")
    
    if response.status_code != 200:
        raise ValueError(f"OpenAI API 错误 {response.status_code}: {response.text}")
    
    result = response.json()
    image_data = result.get("data", [{}])[0]
    
    # 优先返回 base64，其次 URL
    if image_data.get("b64_json"):
        logger.info(f"[OpenAI] 返回 base64 数据")
        return image_data["b64_json"]
    if image_data.get("url"):
        logger.info(f"[OpenAI] 返回 URL: {image_data['url']}")
        return image_data["url"]
    
    raise ValueError(f"OpenAI API 返回结果中既无 url 也无 b64_json: {result}")


def call_image_api(image_path: str | None, prompt: str) -> str:
    """
    根据 IMAGE_MODEL 自动选择 API 格式调用生图接口。
    返回图片 URL 或 base64 数据。
    """
    model = os.getenv("IMAGE_MODEL", "gpt-image-2")
    
    sep = "=" * 60
    logger.info("")
    logger.info(sep)
    logger.info(f"[DEBUG] 代码版本: {CODE_VERSION}")
    logger.info(f"[DEBUG] MODEL: {model}")
    logger.info(f"[DEBUG] IMAGE_PATH: {image_path}")
    prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
    logger.info(f"[DEBUG] PROMPT: {prompt_preview}")
    logger.info(sep)
    
    # 根据模型名选择 API 格式
    if "gemini" in model.lower():
        return call_gemini_api(image_path, prompt)
    else:
        return call_openai_api(image_path, prompt)



def save_output_image(url_or_b64: str, task_id: str, card_index: int) -> str:
    """将生图结果保存到本地 outputs/{task_id}/"""
    out_dir = OUTPUT_DIR / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"card_{card_index}_{uuid.uuid4().hex[:8]}.png"
    filepath = out_dir / filename

    # 判断是 URL 还是 base64
    if url_or_b64.startswith("http://") or url_or_b64.startswith("https://"):
        # URL 格式，下载图片
        resp = requests.get(url_or_b64, timeout=60)
        resp.raise_for_status()
        filepath.write_bytes(resp.content)
    elif url_or_b64.startswith("data:image"):
        # data URI 格式
        b64_data = url_or_b64.split(",", 1)[1]
        filepath.write_bytes(base64.b64decode(b64_data))
    else:
        # 纯 base64 格式（Gemini 返回的格式）
        filepath.write_bytes(base64.b64decode(url_or_b64))

    return str(filepath)


# ── 路由 ───────────────────────────────────────────────────────
@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    """获取任务列表"""
    return jsonify(list_all_tasks())


@app.route("/api/tasks", methods=["POST"])
def create_task():
    """创建新任务"""
    data = request.get_json(silent=True) or {}
    task_id = uuid.uuid4().hex
    task = {
        "id":         task_id,
        "name":       data.get("name", f"任务 {len(list_all_tasks())+1}"),
        "created_at": datetime.utcnow().isoformat(),
        "cards":      data.get("cards", []),
        "json_input": data.get("json_input", ""),
    }
    save_task(task)  # 立即持久化
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    """获取单个任务"""
    task = load_task(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(task)


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id):
    """更新任务（实时持久化）"""
    task = load_task(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    
    data = request.get_json(silent=True) or {}
    
    # 更新允许修改的字段
    if "name" in data:
        task["name"] = data["name"]
    if "cards" in data:
        task["cards"] = data["cards"]
    if "json_input" in data:
        task["json_input"] = data["json_input"]
    
    # 立即持久化
    if save_task(task):
        return jsonify(task)
    else:
        return jsonify({"error": "保存失败"}), 500


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """删除任务"""
    delete_task_file(task_id)
    return jsonify({"ok": True})


@app.route("/api/upload", methods=["POST"])
def upload_image():
    """上传图片"""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    file = request.files["file"]
    ext  = Path(file.filename).suffix or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = UPLOAD_DIR / filename
    file.save(save_path)
    return jsonify({"path": str(save_path), "filename": filename})


@app.route("/api/generate", methods=["POST"])
def generate():
    """生成图片"""
    data       = request.json or {}
    prompt     = data.get("prompt", "")
    image_path = data.get("image_path")   # 可以为 None
    task_id    = data.get("task_id", "default")
    card_index = data.get("card_index", 0)

    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    # 处理图片路径（相对路径转绝对路径）
    if image_path:
        # 如果是相对路径，转换为绝对路径
        if not Path(image_path).is_absolute():
            image_path = str(Path.cwd() / image_path)
        print(f"图片路径: {image_path}, 存在: {Path(image_path).exists()}")

    try:
        result_url = call_image_api(image_path, prompt)
        local_path = save_output_image(result_url, task_id, card_index)
        return jsonify({"url": result_url, "local_path": local_path})
    except Exception as e:
        print(f"生成图片失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    file_path = OUTPUT_DIR / filename
    if file_path.is_dir():
        files = []
        for f in sorted(file_path.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                files.append({"name": f.name, "url": f"/outputs/{filename}/{f.name}", "size": f.stat().st_size})
        
        task_id = filename.strip("/")
        items = ""
        for item in files:
            items += '<li><a href="{}" target="_blank">{}</a><span class="size">{:,} bytes</span></li>'.format(item["url"], item["name"], item["size"])
        if not files:
            items = '<li class="empty">No files yet</li>'
        
        return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Output - {}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:20px;background:#1a1a2e;color:#eee}}
h1{{font-size:18px;color:#7289da}}
ul{{list-style:none;padding:0}}
li{{margin:8px 0;padding:12px;background:#252540;border-radius:6px}}
a{{color:#7289da;text-decoration:none}}
a:hover{{text-decoration:underline}}
.size{{color:#888;font-size:12px;margin-left:10px}}
.empty{{color:#888;padding:40px;text-align:center}}
</style>
</head>
<body>
<h1>📁 Output Folder: {}</h1>
<ul>{}</ul>
</body>
</html>""".format(task_id, task_id, items)
    return send_from_directory(OUTPUT_DIR, filename)


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    """提供上传文件"""
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/")
def index():
    """首页"""
    return render_template("index.html")


# ── 启动 ───────────────────────────────────────────────────────
@app.route("/api/tasks/<task_id>/open_folder")
def open_output_folder(task_id):
    """打开任务的输出文件夹"""
    import subprocess
    import platform
    
    task_dir = OUTPUT_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在
    
    abs_path = task_dir.resolve()
    
    if platform.system() == "Windows":
        subprocess.run(["explorer", str(abs_path)])
    elif platform.system() == "Darwin":  # macOS
        subprocess.run(["open", str(abs_path)])
    else:  # Linux
        subprocess.run(["xdg-open", str(abs_path)])
    
    return jsonify({"ok": True, "path": str(abs_path)})

if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)

@app.route("/api/tasks/<task_id>/outputs")
def list_task_outputs(task_id):
    """列出任务的输出文件"""
    task_dir = OUTPUT_DIR / task_id
    if not task_dir.exists():
        return jsonify([])
    
    files = []
    for f in sorted(task_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append({
                "name": f.name,
                "url": f"/outputs/{task_id}/{f.name}",
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime
            })
    return jsonify(files)


