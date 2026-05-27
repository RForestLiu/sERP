"""
Product 域 - HTTP 接口层（Flask Blueprint）。
"""
from flask import Blueprint, request, jsonify, send_from_directory
from urllib.parse import urlparse

from src.serp.shared import NotFoundError, ValidationError
from ..facade import ProductFacade


def create_product_blueprint(facade: ProductFacade, data_root: str = "", settings_facade=None) -> Blueprint:
    """创建 product 域蓝图"""
    bp = Blueprint("product", __name__, url_prefix="/api")

    # ── 产品 CRUD ──

    @bp.route("/products", methods=["GET"])
    def list_products():
        query = request.args.get("query", "")
        platform = request.args.get("platform", "")
        try:
            products = facade.list_products(query=query, platform=platform)
            stores = settings_facade.get_stores() if settings_facade else []
            return jsonify({"products": products, "stores": stores})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>", methods=["GET"])
    def get_product(skc):
        try:
            product = facade.get_product(skc)
            return jsonify(product)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/manual", methods=["PUT"])
    def update_product_manual(skc):
        data = request.get_json() or {}
        try:
            result = facade.update_manual(skc, data)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>", methods=["DELETE"])
    def delete_product(skc):
        try:
            facade.delete_product(skc)
            return jsonify({"success": True, "skc": skc})
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 规格提取 ──

    @bp.route("/products/<skc>/collect_specs", methods=["POST"])
    def collect_product_specs(skc):
        try:
            result = facade.extract_specs(skc)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/auto_extract", methods=["POST"])
    def auto_extract_product(skc):
        try:
            result = facade.auto_extract(skc)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/extract_from_text", methods=["POST"])
    def extract_from_text():
        data = request.get_json() or {}
        text = (data.get("text", "") or "").strip()
        try:
            result = facade.extract_from_text(text)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 店铺状态 ──

    @bp.route("/products/<skc>/store_status", methods=["PUT"])
    def update_product_store_status(skc):
        data = request.get_json() or {}
        try:
            result = facade.update_store_status(skc, data)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 关键属性审批 ──

    @bp.route("/products/<skc>/propose-change", methods=["POST"])
    def propose_critical_change(skc):
        data = request.get_json() or {}
        try:
            result = facade.propose_critical_change(
                skc=skc,
                field=data.get("field", ""),
                new_value=data.get("new_value"),
                requested_by=data.get("requested_by", ""),
            )
            return jsonify(result)
        except (NotFoundError, ValueError) as e:
            return jsonify({"error": str(e)}), 404
        except ValidationError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/approve/<approval_id>", methods=["POST"])
    def approve_change(skc, approval_id):
        data = request.get_json() or {}
        try:
            result = facade.approve_change(
                skc=skc,
                approval_id=approval_id,
                approved_by=data.get("approved_by", ""),
            )
            return jsonify(result)
        except (NotFoundError, ValueError) as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/reject/<approval_id>", methods=["POST"])
    def reject_change(skc, approval_id):
        data = request.get_json() or {}
        try:
            result = facade.reject_change(
                skc=skc,
                approval_id=approval_id,
                approved_by=data.get("approved_by", ""),
                reason=data.get("reason", ""),
            )
            return jsonify(result)
        except (NotFoundError, ValueError) as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/pending-approvals", methods=["GET"])
    def list_pending_approvals():
        skc = request.args.get("skc")
        try:
            result = facade.list_pending_approvals(skc=skc)
            return jsonify({"pending_approvals": result})
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 图片 / 视频 ──

    @bp.route("/products/<skc>/images", methods=["GET"])
    def get_product_images(skc):
        try:
            result = facade.get_images(skc)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/image-sets", methods=["GET"])
    def get_product_image_sets(skc):
        try:
            result = facade.get_image_sets(skc)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/image-sets", methods=["PUT"])
    def update_product_image_sets(skc):
        data = request.get_json(silent=True) or {}
        try:
            result = facade.update_image_sets(skc, data)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/products/<skc>/images/upload", methods=["POST"])
    def upload_product_image(skc):
        if "file" not in request.files:
            return jsonify({"error": "未提供文件"}), 400
        file = request.files["file"]
        if not file.filename:
            return jsonify({"error": "文件名为空"}), 400
        # Inject set_name from form data for the application service
        set_name = request.form.get("set_name", "采集图片")
        sub_name = request.form.get("sub_name", "")
        file.set_name = set_name
        file.sub_name = sub_name
        try:
            result = facade.upload_image(skc, file)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 视频上传 ──

    @bp.route("/products/<skc>/images/copy_to_clipboard", methods=["POST"])
    def copy_product_images_to_clipboard(skc):
        data = request.get_json(silent=True) or {}
        filenames = data.get("filenames", [])
        if not isinstance(filenames, list):
            return jsonify({"error": "filenames 必须是数组"}), 400
        try:
            result = facade.copy_images_to_clipboard(skc, filenames)
            if "error" in result:
                return jsonify(result), 400
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/upload-video", methods=["POST"])
    def upload_video():
        if "file" not in request.files:
            return jsonify({"error": "未提供文件"}), 400
        file = request.files["file"]
        skc = request.form.get("skc", "common")
        if not file.filename:
            return jsonify({"error": "文件名为空"}), 400
        try:
            result = facade.upload_video(skc, file)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── 图片代理 ──

    @bp.route("/img_proxy")
    def img_proxy():
        url = request.args.get("url", "")
        if not url:
            return "", 400
        domain = urlparse(url).hostname or ""
        allowed = frozenset({
            "m.media-amazon.com", "images-na.ssl-images-amazon.com",
            "images-eu.ssl-images-amazon.com", "images-fe.ssl-images-amazon.com",
            "img.alicdn.com", "cbu01.alicdn.com",
            "images.wbstatic.net", "basket.wildberries.ru",
            "cdn1.ozonusercontent.com", "cdn2.ozonusercontent.com",
        })
        if domain not in allowed:
            return "", 403
        try:
            content = facade.proxy_image(url)
            return content, 200, {"Content-Type": "image/jpeg", "Cache-Control": "public, max-age=86400"}
        except Exception:
            return "", 502

    return bp


def create_product_static_blueprint(facade: ProductFacade, data_root: str = "", videos_dir: str = "") -> Blueprint:
    """创建产品静态文件服务蓝图（/product_images/... /videos/... /image-batch/...）。
    这些路由不能用 url_prefix 约束，所以独立成一个蓝图。
    """
    import os
    from flask import render_template
    bp = Blueprint("product_static", __name__)

    @bp.route("/product_images/<skc>/<path:filename>")
    def serve_product_image(skc, filename):
        try:
            product = facade.get_product(skc)
        except Exception:
            return "", 404
        images_dir = product.get("images_dir", "")
        if images_dir and os.path.exists(images_dir):
            return send_from_directory(images_dir, filename)
        return "", 404

    @bp.route("/videos/<skc>/<path:filename>")
    def serve_video(skc, filename):
        video_dir = os.path.join(videos_dir, skc) if videos_dir else os.path.join(data_root, "videos", skc)
        if os.path.exists(video_dir):
            return send_from_directory(video_dir, filename)
        return "", 404

    @bp.route("/image-batch/<skc>")
    def image_batch_page(skc):
        try:
            product = facade.get_product(skc)
        except Exception:
            return "产品不存在", 404
        return render_template("image_batch.html",
                               skc=skc,
                               title=product.get("title", skc),
                               platform=product.get("platform", ""))

    return bp
