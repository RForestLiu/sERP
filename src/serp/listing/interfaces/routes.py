"""
Listing 域 - HTTP 接口层（Flask Blueprint）。
只负责请求/响应适配，业务逻辑完全委托给 ListingFacade。
"""
from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template

from ..facade import ListingFacade


def create_listing_blueprint(facade: ListingFacade) -> Blueprint:
    """创建 listing 域蓝图"""
    bp = Blueprint("listing", __name__, url_prefix="/api")

    # ── 草稿管理 ──

    @bp.route("/listings/<skc>/<store_id>", methods=["GET"])
    def get_draft(skc, store_id):
        result = facade.get_draft(skc, store_id)
        return jsonify(result)

    @bp.route("/listings/<skc>/<store_id>", methods=["PUT"])
    def save_draft(skc, store_id):
        data = request.get_json()
        if not data:
            return jsonify({"error": "数据不能为空"}), 400
        data["skc"] = skc
        data["store_id"] = store_id
        result = facade.save_draft(skc, store_id, data)
        return jsonify(result)

    @bp.route("/listings/<skc>/<store_id>", methods=["DELETE"])
    def delete_draft(skc, store_id):
        result = facade.delete_draft(skc, store_id)
        return jsonify(result)

    # ── Ozon 上架 API ──

    @bp.route("/ozon/<store_id>/listing/simulate", methods=["POST"])
    def listing_simulate(store_id):
        data = request.get_json() or {}
        result = facade.simulate(store_id, data)
        return jsonify(result)

    @bp.route("/ozon/<store_id>/product/create", methods=["POST"])
    def product_create(store_id):
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "请求数据不能为空"}), 400
        result = facade.create_product(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 400 if "quality_report" not in result else 502
        return jsonify(result)

    @bp.route("/ozon/<store_id>/sync-products", methods=["POST"])
    def sync_products(store_id):
        data = request.get_json() or {}
        result = facade.sync_products(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 502
        return jsonify(result)

    @bp.route("/ozon/<store_id>/listing/auto-category", methods=["POST"])
    def workbench_auto_category(store_id):
        data = request.get_json() or {}
        result = facade.auto_category(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/ozon/<store_id>/listing/generate-draft", methods=["POST"])
    def workbench_generate_draft(store_id):
        data = request.get_json() or {}
        result = facade.generate_workbench_draft(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/ozon/<store_id>/listing/validate", methods=["POST"])
    def workbench_validate(store_id):
        data = request.get_json() or {}
        result = facade.validate_workbench_payload(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/ozon/<store_id>/listing/prepare-images", methods=["POST"])
    def workbench_prepare_images(store_id):
        data = request.get_json() or {}
        data.setdefault("base_url", request.host_url.rstrip("/"))
        result = facade.prepare_images(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/ozon/<store_id>/listing/upsert", methods=["POST"])
    def workbench_upsert(store_id):
        data = request.get_json() or {}
        result = facade.upsert_workbench(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/ozon/<store_id>/listing/official-rating", methods=["POST"])
    def workbench_official_rating(store_id):
        data = request.get_json() or {}
        result = facade.official_rating(store_id, data)
        if result.get("success") is False:
            return jsonify(result), 502
        return jsonify(result)

    # ── Ozon 导入状态查询 ──

    @bp.route("/ozon/<store_id>/listing/check-import", methods=["GET"])
    def check_import_status(store_id):
        task_id = request.args.get("task_id", "")
        if not task_id:
            return jsonify({"success": False, "error": "缺少 task_id 参数"}), 400
        result = facade.check_import_status(store_id, task_id)
        if result.get("success") is False:
            return jsonify(result), 502
        return jsonify(result)

    # ── AI 自动填充 ──

    @bp.route("/ozon/<store_id>/listing/content-rating", methods=["POST"])
    def content_rating(store_id):
        data = request.get_json() or {}
        skus = data.get("skus") or []
        if isinstance(skus, str):
            skus = [s.strip() for s in skus.split(",") if s.strip()]
        result = facade.get_content_rating(store_id, skus)
        if result.get("success") is False:
            return jsonify(result), 502
        return jsonify(result)

    @bp.route("/auto-fill/analyze", methods=["POST"])
    def auto_fill_analyze():
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求数据不能为空"}), 400
        result = facade.analyze_for_autofill(data)
        if "error" in result:
            status = 400 if result["error"] == "表单字段列表不能为空" else 500
            return jsonify(result), status
        return jsonify(result)

    @bp.route("/auto-fill/ozon-fields", methods=["POST"])
    def auto_fill_ozon_fields():
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求数据不能为空"}), 400
        result = facade.fill_ozon_fields(data)
        if "error" in result:
            status = 400 if result["error"] == "Ozon 属性列表不能为空" else 500
            return jsonify(result), status
        return jsonify(result)

    return bp


def create_listing_page_blueprint() -> Blueprint:
    """创建 listing 页面蓝图（/ozon-listing /listing-workbench /product-maintenance /knowledge-base）"""
    bp = Blueprint("listing_page", __name__)

    @bp.route("/ozon-listing")
    def ozon_listing_page():
        return render_template("ozon_listing.html")

    @bp.route("/listing-workbench")
    def listing_workbench_page():
        return render_template("listing_workbench.html")

    @bp.route("/product-maintenance")
    def product_maintenance_page():
        return render_template("product_maintenance.html")

    @bp.route("/knowledge-base")
    def knowledge_base_page():
        return render_template("knowledge_base.html")

    return bp
