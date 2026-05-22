"""
Settings 域 - HTTP 接口层（Flask Blueprint）。
只负责请求/响应适配，业务逻辑完全委托给 SettingsFacade。
"""
from flask import Blueprint, request, jsonify

from ..facade import SettingsFacade


def create_settings_blueprint(facade: SettingsFacade) -> Blueprint:
    """创建 settings 域蓝图"""
    bp = Blueprint("settings", __name__, url_prefix="/api/settings")

    @bp.route("", methods=["GET"])
    def get_settings():
        view = facade.get_view()
        return jsonify({
            "models": view.models,
            "feature_models": view.feature_models,
            "pricing_formulas": view.pricing_formulas,
            "env": view.env,
            "stores": view.stores,
            "feature_model_keys": view.feature_model_keys,
        })

    @bp.route("", methods=["PUT"])
    def update_settings():
        data = request.get_json() or {}
        result = facade.update(data)
        return jsonify(result)

    @bp.route("/export", methods=["GET"])
    def export_settings():
        include_secrets = request.args.get("include_secrets") == "1"
        dto = facade.export_payload(include_secrets=include_secrets)
        return jsonify({
            "settings": dto.settings,
            "stores": dto.stores,
            "env": dto.env,
            "meta": dto.meta,
        })

    @bp.route("/import", methods=["POST"])
    def import_settings():
        data = request.get_json() or {}
        payload = data.get("payload") or data
        if not isinstance(payload, dict):
            return jsonify({"error": "导入内容必须是 JSON 对象"}), 400

        if data.get("preview", True):
            preview = facade.preview_import(payload)
            return jsonify({
                "models_diff": preview.models_diff,
                "feature_models_diff": preview.feature_models_diff,
                "pricing_formulas_diff": preview.pricing_formulas_diff,
                "stores_diff": preview.stores_diff,
                "env_diff": preview.env_diff,
                "summary": preview.summary,
            })

        result = facade.apply_import(payload)
        if result.success:
            return jsonify({
                "success": True,
                "summary": result.summary,
                "restart_required": result.restart_required,
            })
        return jsonify({
            "success": False,
            "errors": result.errors,
            "summary": result.summary,
        }), 400

    return bp
