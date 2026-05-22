"""
ImageTask 域 - HTTP 接口层（Flask Blueprint）。
只负责请求/响应适配，业务逻辑完全委托给 ImageTaskFacade。
"""
from __future__ import annotations

from flask import Blueprint, request, jsonify

from ..facade import ImageTaskFacade
from ..application.commands import ImageTaskApplicationService


def create_imagetask_blueprint(facade: ImageTaskFacade) -> Blueprint:
    """创建 imagetask 域蓝图"""
    bp = Blueprint("imagetask", __name__, url_prefix="/api")

    app_service = facade  # type hint convenience

    # ── 任务类型 ──

    @bp.route("/task-types", methods=["GET"])
    def get_task_types():
        types = facade.list_task_types()
        return jsonify(types)

    # ── 任务 CRUD ──

    @bp.route("/tasks", methods=["GET"])
    def get_tasks():
        tasks = facade.list_tasks()
        return jsonify(tasks)

    @bp.route("/tasks", methods=["POST"])
    def create_task():
        payload = request.get_json(silent=True) or {}
        result = facade.create_task(payload)
        return jsonify(result)

    @bp.route("/tasks/<task_id>", methods=["GET"])
    def get_task(task_id):
        result = facade.get_task(task_id)
        return jsonify(result)

    @bp.route("/tasks/<task_id>", methods=["PUT"])
    def update_task(task_id):
        payload = request.get_json() or {}
        result = facade.update_task(task_id, payload)
        return jsonify(result)

    @bp.route("/tasks/<task_id>", methods=["DELETE"])
    def delete_task(task_id):
        facade.delete_task(task_id)
        return jsonify({"deleted": task_id})

    # ── 图片操作 ──

    @bp.route("/tasks/<task_id>/upload_source_images", methods=["POST"])
    def upload_source_images(task_id):
        files = request.files.getlist("images")
        result = facade.upload_source_images(task_id, files)
        return jsonify(result)

    @bp.route("/tasks/<task_id>/upload_ref_image/<int:ref_index>", methods=["POST"])
    def upload_ref_image(task_id, ref_index):
        f = request.files.get("image")
        result = facade.upload_ref_image(task_id, ref_index, f)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/tasks/<task_id>/import_images", methods=["POST"])
    def import_images_to_task(task_id):
        """将产品图片复制到任务 source_images 目录"""
        data = request.get_json() or {}
        skc = data.get("skc", "")
        entries = data.get("entries", [])
        if isinstance(facade, ImageTaskApplicationService):
            result = facade._import_images_from_product(task_id, skc, entries)
        else:
            result = facade.import_images(task_id, [])
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/generate", methods=["POST"])
    def generate_image():
        data = request.get_json() or {}
        # /generate uses task_id from the payload body
        task_id = data.get("task_id", "")
        result = facade.generate(task_id, data)
        if "error" in result:
            code = 500
            if "not configured" in str(result.get("error", "")):
                code = 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/tasks/<task_id>/save_images", methods=["POST"])
    def save_images(task_id):
        data = request.get_json() or {}
        result = facade.save_images(task_id, data)
        return jsonify(result)

    @bp.route("/tasks/<task_id>/compress_images", methods=["POST"])
    def compress_task_images(task_id):
        data = request.get_json() or {}
        result = facade.compress_images(task_id, data)
        return jsonify(result)

    # ── 导出 ──

    @bp.route("/tasks/<task_id>/save_to_product", methods=["POST"])
    def save_to_product(task_id):
        data = request.get_json() or {}
        result = facade.save_to_product(task_id, data)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/tasks/<task_id>/copy_to_clipboard", methods=["POST"])
    def copy_task_images_to_clipboard(task_id):
        data = request.get_json() or {}
        img_type = data.get("type", "source")
        if isinstance(facade, ImageTaskApplicationService):
            result = facade._copy_to_clipboard_with_type(task_id, img_type)
        else:
            result = facade.copy_to_clipboard(task_id)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/tasks/<task_id>/open_folder", methods=["POST"])
    def open_folder(task_id):
        facade.open_folder(task_id)
        return jsonify({"status": "opened", "folder": "generated"})

    return bp
