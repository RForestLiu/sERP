"""
Logistics 域 - HTTP 接口层（Flask Blueprint）。
"""
from flask import Blueprint, request, jsonify

from ..facade import LogisticsFacade


def create_logistics_blueprint(facade: LogisticsFacade) -> Blueprint:
    bp = Blueprint("logistics", __name__, url_prefix="/api/logistics")

    @bp.route("/templates", methods=["GET"])
    def list_templates():
        templates = facade.list_templates()
        return jsonify({"templates": templates})

    @bp.route("/calculate", methods=["POST"])
    def calculate():
        data = request.get_json(silent=True) or {}
        result = facade.calculate(data)
        if "error" in result:
            status = 400 if "必须大于" in result["error"] else 404
            return jsonify(result), status
        return jsonify(result)

    return bp
