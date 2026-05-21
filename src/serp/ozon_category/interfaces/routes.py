"""
OzonCategory 域 - HTTP 接口层（Flask Blueprint）。
"""
from __future__ import annotations

import logging

from flask import Blueprint, request, jsonify

from ..facade import OzonCategoryFacade

logger = logging.getLogger(__name__)


def create_ozon_category_blueprint(facade: OzonCategoryFacade) -> Blueprint:
    """创建 ozon_category 域蓝图"""
    bp = Blueprint("ozon_category", __name__, url_prefix="/api/ozon")

    @bp.route("/<store_id>/category-tree", methods=["GET"])
    def get_category_tree(store_id):
        """获取 Ozon 全品类树（带缓存）"""
        try:
            result = facade.get_category_tree(store_id)
            return jsonify(result)
        except Exception as e:
            logger.error("[品类树] 获取失败: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/<store_id>/translate-categories", methods=["POST"])
    def translate_categories(store_id):
        """
        批量翻译品类名（俄语→中文），带缓存。
        请求体: {"category_ids": [123, 456, ...]}
        """
        try:
            data = request.get_json() or {}
            category_ids = data.get("category_ids") or data.get("categories", [])
            if isinstance(category_ids[0], dict) if category_ids else False:
                # 兼容旧格式: [{"id": 123, "name": "...", "path": "..."}]
                category_ids = [c.get("id") for c in category_ids if isinstance(c, dict)]

            if not category_ids:
                return jsonify({"error": "category_ids 不能为空"}), 400

            result = facade.translate_categories(store_id, category_ids)
            return jsonify(result)
        except Exception as e:
            logger.error("[翻译] 失败: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/<store_id>/refresh-categories", methods=["POST"])
    def refresh_categories(store_id):
        """一键刷新品类树 + 批量翻译（后台异步）"""
        try:
            result = facade.refresh_categories(store_id)
            return jsonify(result)
        except Exception as e:
            logger.error("[刷新] 启动失败: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/<store_id>/refresh-categories/status", methods=["GET"])
    def get_refresh_status(store_id):
        """查询品类树刷新任务进度"""
        try:
            result = facade.get_refresh_status(store_id)
            return jsonify(result)
        except Exception as e:
            logger.error("[刷新状态] 查询失败: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/<store_id>/match-category", methods=["POST"])
    def match_category(store_id):
        """根据产品信息自动匹配最合适的 Ozon 品类"""
        try:
            data = request.get_json() or {}
            product_info = {
                "product_title": data.get("product_title", ""),
                "product_category": data.get("product_category", ""),
                "product_description": data.get("product_description", ""),
            }
            result = facade.match_category(store_id, product_info)
            return jsonify(result)
        except Exception as e:
            logger.error("[匹配] 失败: %s", e)
            return jsonify({"error": str(e)}), 500

    @bp.route("/<store_id>/category-attributes", methods=["POST"])
    def get_category_attributes(store_id):
        """获取 Ozon 品类属性列表"""
        try:
            data = request.get_json() or {}
            category_id = data.get("description_category_id", 0)
            if not category_id:
                return jsonify({"error": "请提供 description_category_id"}), 400

            result = facade.get_category_attributes(store_id, int(category_id))
            return jsonify(result)
        except Exception as e:
            logger.error("[属性] 获取失败: %s", e)
            return jsonify({"error": str(e)}), 500

    return bp
