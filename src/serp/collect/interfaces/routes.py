"""
Collect 域 - HTTP 接口层（Flask Blueprint）。
只负责请求/响应适配，业务逻辑完全委托给 CollectFacade。
"""
import os
import subprocess
import sys

from flask import Blueprint, request, jsonify
from flask_cors import cross_origin

from ..facade import CollectFacade


def create_collect_blueprint(facade: CollectFacade, data_root: str = "") -> Blueprint:
    """创建 collect 域蓝图"""
    bp = Blueprint("collect", __name__, url_prefix="/api/collect")

    @bp.route("/tasks", methods=["GET"])
    def list_tasks():
        tasks = facade.list_tasks()
        return jsonify(tasks)

    @bp.route("", methods=["POST"])
    def start_collect():
        data = request.get_json() or {}
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "请输入采集网址"}), 400
        result = facade.start(url)
        return jsonify(result)

    @bp.route("/amazon_capture", methods=["POST"])
    @cross_origin()
    def amazon_capture():
        data = request.get_json()
        if not data:
            return jsonify({"error": "no data"}), 400
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "no title"}), 400
        result = facade.capture_amazon(
            url=data.get("url", ""),
            html="",
            settings=data,
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200

    @bp.route("/browser_capture", methods=["POST"])
    @cross_origin()
    def browser_capture():
        data = request.get_json()
        if not data:
            return jsonify({"error": "no data"}), 400
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "no title"}), 400
        import json as _json
        result = facade.capture_browser(
            html=_json.dumps(data, ensure_ascii=False),
            url=data.get("url", ""),
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200

    @bp.route("/send_html", methods=["POST", "OPTIONS"])
    @cross_origin()
    def send_html():
        data = request.get_json()
        if not data:
            return jsonify({"error": "no data"}), 400
        html_content = data.get("html", "")
        if not html_content:
            return jsonify({"error": "no html"}), 400
        result = facade.save_html(
            html=html_content,
            url=data.get("url", ""),
        )
        return jsonify(result), 200

    @bp.route("/dxm_capture", methods=["POST"])
    def dxm_capture():
        data = request.get_json()
        if not data:
            return jsonify({"error": "no data"}), 400
        result = facade.capture_dxm(data=data, store_id=data.get("store_id", ""))
        return jsonify(result), 200

    @bp.route("/<task_id>/status", methods=["GET"])
    def get_status(task_id):
        result = facade.get_status(task_id)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/<task_id>/result", methods=["GET"])
    def get_result(task_id):
        result = facade.get_result(task_id)
        if "error" in result:
            return jsonify(result), 400 if "status" in result else 404
        return jsonify(result)

    @bp.route("/<task_id>/open_folder", methods=["POST"])
    def open_folder(task_id):
        folder = os.path.join(data_root, f"collect_{task_id}")
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

    @bp.route("/<task_id>/product_status", methods=["GET"])
    def get_product_status(task_id):
        result = facade.get_product_status(task_id)
        return jsonify(result)

    @bp.route("/<task_id>", methods=["DELETE"])
    def delete_task(task_id):
        result = facade.delete_task(task_id)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/<task_id>/save_product", methods=["POST"])
    def save_product(task_id):
        result = facade.save_to_product(task_id)
        if result.get("success"):
            return jsonify(result)
        status_code = 409 if "已保存" in str(result.get("error", "")) else 400
        if "不存在" in str(result.get("error", "")):
            status_code = 404
        return jsonify(result), status_code

    return bp
