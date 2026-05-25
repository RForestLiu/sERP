"""
Collect 域 - 捕获引擎（浏览器扩展数据接收处理）。

处理来自 Chrome 扩展的各种捕获数据：
- Amazon 商品捕获
- 通用浏览器捕获（多平台、变体支持）
- DXM 店小秘截获数据
- HTML 快照保存
"""
import os
import json
import re
import logging
import threading
import uuid as uuid_lib
from datetime import datetime

from src.serp.shared import EventBus
from ..domain.entities import CollectTask
from ..domain.value_objects import TaskId, platform_prefix as _platform_prefix, platform_referer
from ..domain.services import UrlService
from ..domain.repositories import CollectTaskRepository
from ..domain.events import TaskStarted, TaskCompleted as TaskCompletedEvent

logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _compact_variant_entry(variant):
    """保留变体业务信息，移除图片 URL 等采集噪声。"""
    if not isinstance(variant, dict):
        return {}
    keep_keys = (
        "variantName", "price", "variantInfo", "currentVariant",
        "product_details", "product_description", "_error",
    )
    compact = {k: variant.get(k) for k in keep_keys if variant.get(k) not in (None, "", [], {})}
    images = variant.get("images", [])
    if isinstance(images, list) and images:
        compact["image_count"] = len(images)
    return compact


def _sanitize_product_payload(data):
    """产品数据只保留可填表/可展示的信息"""
    sanitized = dict(data)
    sanitized["images"] = []
    if sanitized.get("variantData"):
        sanitized["variantData"] = [
            _compact_variant_entry(v) for v in sanitized["variantData"]
            if isinstance(v, dict)
        ]
    return sanitized


def _clean_product_payload(data, settings_facade):
    sanitized = _sanitize_product_payload(data)
    if not settings_facade:
        description = "\n".join(
            str(sanitized.get(k, "")).strip()
            for k in ("about_item", "product_description", "description")
            if str(sanitized.get(k, "")).strip()
        )
        return {
            "product_data": {
                "product_param": sanitized.get("product_details", {}) if isinstance(sanitized.get("product_details"), dict) else {},
                "product_description": description,
            },
            "raw_product_data": sanitized,
            "clean_audit": {"status": "skipped", "reason": "settings facade unavailable"},
        }
    from .product_data_cleaner import ProductDataCleaner
    return ProductDataCleaner(settings_facade).clean(sanitized)


class CaptureEngine:
    """捕获引擎 — 处理浏览器扩展回传的数据"""

    @staticmethod
    def amazon_capture(html: str, settings: dict, task_repo: CollectTaskRepository,
                       event_bus: EventBus, data_root: str, settings_facade=None) -> dict:
        """接收 Chrome 扩展从 Amazon 页面提取的产品数据"""
        data = settings

        title = data.get("title", "").strip()
        if not title:
            return {"error": "no title"}

        tid = TaskId.generate(prefix="amz")
        images = data.get("images", [])
        price = data.get("price", "")
        product_url = data.get("url", "")

        data_dir = os.path.join(data_root, f"collect_{tid.value}")
        images_dir = os.path.join(data_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        sanitized = _clean_product_payload(data, settings_facade)
        product_data_file = os.path.join(data_dir, "product_data.json")
        with open(product_data_file, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)

        task = CollectTask(
            id=tid.value,
            url=product_url,
            platform="amazon",
            source="amazon_extension",
        )
        task.set_as_extension_capture(
            platform="amazon", title=title,
            image_count=len(images), source="amazon_extension",
        )
        task._result["data_dir"] = data_dir
        task._result["product_data"] = product_data_file.replace("\\", "/")
        task._result["images_mapping"] = None
        task._result["images_dir"] = images_dir
        task._result["price"] = price
        task_repo.save(task)
        task_repo.save_all()

        # 后台下载图片
        if images:
            thread = threading.Thread(
                target=CaptureEngine._download_amazon_images,
                args=(tid.value, images, images_dir, task_repo),
                daemon=True,
            )
            thread.start()

        logger.info("[amazon_capture] %s (images=%d)", title, len(images))
        return {
            "status": "ok",
            "task_id": tid.value,
            "title": title,
            "image_count": len(images),
        }

    @staticmethod
    def browser_capture(html: str, url: str, task_repo: CollectTaskRepository,
                        event_bus: EventBus, data_root: str, settings_facade=None) -> dict:
        """接收 Chrome 扩展从多平台提取的产品数据（支持批量变体）"""
        data = {}
        try:
            data = json.loads(html) if isinstance(html, str) else html
        except json.JSONDecodeError:
            return {"error": "invalid json"}

        title = data.get("title", "").strip()
        if not title:
            return {"error": "no title"}

        platform = data.get("platform", "unknown")
        prefix = _platform_prefix(platform)
        tid = TaskId.generate(prefix=prefix)

        images = data.get("images", [])
        price = data.get("price", "")
        product_url = data.get("url", url or "")
        variant_data = data.get("variantData")
        variant_count = len(variant_data) if variant_data else 0

        data_dir = os.path.join(data_root, f"collect_{tid.value}")
        images_dir = os.path.join(data_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        product_data_file = os.path.join(data_dir, "product_data.json")
        sanitized = _clean_product_payload(data, settings_facade)
        with open(product_data_file, "w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)

        total_image_count = len(images)
        if variant_data:
            for v in variant_data:
                total_image_count += len(v.get("images", []))

        task = CollectTask(
            id=tid.value,
            url=product_url,
            platform=platform,
            source="browser_extension",
        )
        task.set_as_extension_capture(
            platform=platform, title=title,
            image_count=len(images), variant_count=variant_count,
            source="browser_extension",
        )
        task._result["data_dir"] = data_dir
        task._result["product_data"] = product_data_file.replace("\\", "/")
        task._result["images_mapping"] = None
        task._result["images_dir"] = images_dir
        task._result["price"] = price
        task._result["variant_count"] = variant_count
        task._result["total_image_count"] = total_image_count
        task._result["variants"] = [
            _compact_variant_entry(v) for v in variant_data
        ] if variant_data else []
        task_repo.save(task)
        task_repo.save_all()

        # 所有产品统一变体结构
        if not variant_data:
            variant_data = [{"variantName": "default", "price": price, "images": images, "url": product_url}]
            images = []

        if variant_data:
            thread = threading.Thread(
                target=CaptureEngine._download_variant_images,
                args=(tid.value, variant_data, images_dir, platform, task_repo),
                daemon=True,
            )
            thread.start()

        logger.info("[browser_capture] [%s] %s (variants=%d, images=%d)",
                    platform, title, variant_count, total_image_count)
        return {
            "status": "ok",
            "task_id": tid.value,
            "title": title,
            "platform": platform,
            "variant_count": variant_count,
            "image_count": total_image_count,
        }

    @staticmethod
    def dxm_capture(data: dict, store_id: str, task_repo: CollectTaskRepository,
                    event_bus: EventBus, data_root: str,
                    run_collect_in_thread) -> dict:
        """接收 Chrome 扩展截获的店小秘采集 API 数据"""
        url = data.get("url", "")
        page_url = data.get("pageUrl", "")

        resp_body = data.get("responseBody") or data.get("responseText") or {}
        if isinstance(resp_body, str):
            try:
                resp_body = json.loads(resp_body)
            except (json.JSONDecodeError, ValueError):
                resp_body = {}

        req_body = data.get("requestBody") or {}

        # 保存调试日志
        CaptureEngine._log_dxm_capture(data, resp_body or req_body, data_root)

        # 尝试从响应体中提取产品数据
        product_data = CaptureEngine._extract_dxm_product(resp_body, url, page_url)
        if product_data:
            CaptureEngine._create_dxm_task(product_data, task_repo, data_root)
            return {"status": "ok", "task_id": "dxm_created", "title": product_data.get("title")}

        # 尝试从请求体提取目标 URL 触发自主采集
        target_url = UrlService.extract_target_url(req_body)
        if target_url:
            logger.info("[dxm_capture] triggering autonomous collection: %s", target_url)
            tid = TaskId.generate(prefix="collect")
            thread = threading.Thread(
                target=run_collect_in_thread,
                args=(target_url, tid.value),
                daemon=True,
            )
            thread.start()
            return {"status": "ok", "task_id": tid.value, "message": "已触发自主采集"}

        return {"status": "ignored", "reason": "no product data found"}

    @staticmethod
    def save_html(html: str, url: str, data_root: str) -> dict:
        """保存 HTML 快照"""
        debug_dir = os.path.join(data_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)

        platform = UrlService.extract_platform(url) if url else "unknown"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        safe_name = re.sub(r"[^a-zA-Z0-9_\-一-鿿]", "_", "")[:60] or "page"
        filename = f"{platform}_{safe_name}_{ts}.html"
        filepath = os.path.join(debug_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info("[save_html] %s: -> %s (%d bytes)", platform, filename, len(html))
        return {"status": "ok", "filename": filename, "size": len(html)}

    # ==================== 后台图片下载 ====================

    @staticmethod
    def _download_amazon_images(task_id, image_urls, images_dir, task_repo):
        """后台下载 Amazon 图片"""
        import requests as req_lib

        downloaded = 0
        failed = 0
        images_mapping = []
        session = req_lib.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.amazon.com/",
        })

        for idx, img_url in enumerate(image_urls):
            try:
                resp = session.get(img_url, timeout=30)
                if resp.status_code == 200:
                    ext = os.path.splitext(img_url.split("?")[0])[1] or ".jpg"
                    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                        ext = ".jpg"
                    filename = f"{idx+1:02d}{ext}"
                    filepath = os.path.join(images_dir, filename)
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
                    images_mapping.append({"index": idx, "url": img_url, "file": filename})
                    downloaded += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        task = task_repo.find_by_id(task_id)
        if task:
            task._result["downloaded"] = downloaded
            task._result["failed"] = failed
            task.message += f" ({downloaded}图已下载)"

        if images_mapping:
            mapping_file = os.path.join(os.path.dirname(images_dir), "images_mapping.json")
            with open(mapping_file, "w", encoding="utf-8") as f:
                json.dump(images_mapping, f, indent=2, ensure_ascii=False)
            if task:
                task._result["images_mapping"] = mapping_file.replace("\\", "/")

        if task:
            task_repo.save_all()
        logger.info("[amazon_capture] %s: %d downloaded, %d failed", task_id, downloaded, failed)

    @staticmethod
    def _download_variant_images(task_id, variant_data, images_dir, platform, task_repo):
        """下载各变体图片到子目录: images/01_Name/, images/02_Name/..."""
        import requests as req_lib

        referer = platform_referer(platform)
        session = req_lib.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": referer,
        })

        def _download_one(url, idx, dest_dir):
            try:
                resp = session.get(url, timeout=30)
                if resp.status_code == 200:
                    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
                    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
                        ext = ".jpg"
                    fname = f"{idx+1:02d}{ext}"
                    fpath = os.path.join(dest_dir, fname)
                    with open(fpath, "wb") as f:
                        f.write(resp.content)
                    return True, fname
            except Exception:
                pass
            return False, None

        total_downloaded = 0
        total_failed = 0
        all_mappings = {}

        for vi, variant in enumerate(variant_data):
            vname = variant.get("variantName", f"variant_{vi}")
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", vname)[:50]
            vdir = os.path.join(images_dir, f"{vi+1:02d}_{safe_name}")
            os.makedirs(vdir, exist_ok=True)

            vimgs = variant.get("images", [])
            mappings = []
            for i2, url in enumerate(vimgs):
                ok, fname = _download_one(url, i2, vdir)
                if ok:
                    mappings.append({"index": i2, "url": url, "file": fname, "subdir": os.path.basename(vdir)})
                    total_downloaded += 1
                else:
                    total_failed += 1
            if mappings:
                all_mappings[vname] = mappings

        task = task_repo.find_by_id(task_id)
        if task:
            task._result["downloaded"] = total_downloaded
            task._result["failed"] = total_failed
            task.message += f" ({total_downloaded}图已下载)"

        if all_mappings:
            mapping_file = os.path.join(os.path.dirname(images_dir), "images_mapping.json")
            with open(mapping_file, "w", encoding="utf-8") as f:
                json.dump(all_mappings, f, indent=2, ensure_ascii=False)
            if task:
                task._result["images_mapping"] = mapping_file.replace("\\", "/")

        if task:
            task_repo.save_all()
        logger.info("[browser_capture] %s [%s]: %d downloaded, %d failed (%d variants)",
                    task_id, platform, total_downloaded, total_failed, len(variant_data))

    # ==================== DXM 产品提取 ====================

    @staticmethod
    def _log_dxm_capture(data, body, data_root):
        """记录所有截获的请求到调试日志"""
        log_file = os.path.join(data_root, "dxm_debug.jsonl")
        try:
            entry = {
                "timestamp": data.get("timestamp", ""),
                "url": data.get("url", ""),
                "pageUrl": data.get("pageUrl", ""),
                "data_keys": list(body.keys()) if isinstance(body, dict) else str(type(body)),
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _extract_dxm_product(response_data, url="", page_url=""):
        """从店小秘 API 响应中提取产品数据"""
        if not isinstance(response_data, dict) or not response_data:
            return None

        # 遍历响应数据寻找产品信息
        candidates = []
        CaptureEngine._walk_find_products(response_data, candidates)

        best = None
        best_images = 0
        for c in candidates:
            ni = len(c.get("images", []))
            if ni > best_images:
                best_images = ni
                best = c

        if best and best.get("title"):
            platform = UrlService.extract_platform(
                best.get("url") or best.get("sourceUrl") or url or page_url or ""
            )
            images = best.get("images", [])
            if isinstance(images, dict):
                images = list(images.values())
            return {
                "title": str(best.get("title", "")),
                "platform": platform,
                "url": str(best.get("url") or best.get("sourceUrl") or url or page_url or ""),
                "image_count": len(images) if isinstance(images, list) else 0,
                "images": images if isinstance(images, list) else [],
                "price": str(best.get("price") or best.get("productPrice") or ""),
                "sku": str(best.get("sku") or best.get("productSku") or ""),
                "raw_response": response_data,
            }
        return None

    @staticmethod
    def _walk_find_products(data, candidates, depth=0):
        """递归遍历 JSON 数据查找产品信息"""
        if depth > 6 or not isinstance(data, (dict, list)):
            return
        if isinstance(data, dict):
            if any(k in data for k in ("title", "name", "productName", "goodsName")):
                candidates.append(data)
            for v in data.values():
                CaptureEngine._walk_find_products(v, candidates, depth + 1)
        elif isinstance(data, list):
            for item in data:
                CaptureEngine._walk_find_products(item, candidates, depth + 1)

    @staticmethod
    def _create_dxm_task(product_data, task_repo, data_root):
        """创建店小秘截获产品任务"""
        tid = TaskId.generate(prefix="dxm")
        title = product_data.get("title", "店小秘采集")
        platform = product_data.get("platform", "unknown")
        image_count = product_data.get("image_count", 0)

        data_dir = os.path.join(data_root, f"collect_{tid.value}")
        os.makedirs(data_dir, exist_ok=True)

        product_data_file = os.path.join(data_dir, "product_data.json")
        with open(product_data_file, "w", encoding="utf-8") as f:
            json.dump(product_data, f, indent=2, ensure_ascii=False)

        task = CollectTask(
            id=tid.value,
            url=product_data.get("url", ""),
            platform=platform,
            source="mitm_dianxiaomi",
        )
        task.set_as_extension_capture(
            platform=platform, title=title,
            image_count=image_count, source="mitm_dianxiaomi",
        )
        task._result["data_dir"] = data_dir
        task._result["product_data"] = product_data_file.replace("\\", "/")
        task._result["images_mapping"] = None
        task._result["images_dir"] = ""
        task._result["downloaded"] = 0
        task._result["failed"] = 0
        task._result["source"] = "mitm_dianxiaomi"
        task_repo.save(task)
        task_repo.save_all()

        logger.info("[dxm_capture] %s (platform=%s, images=%d)", title, platform, image_count)
