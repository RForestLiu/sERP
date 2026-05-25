"""
Collect 域 - 应用服务（用例编排）。
"""
import logging
import threading
import asyncio
import os
import json
import re

from src.serp.shared import EventBus

from ..domain.entities import CollectTask
from ..domain.value_objects import TaskId, platform_prefix
from ..domain.services import CategorizationService, UrlService, CATEGORY_CODES
from ..domain.repositories import CollectTaskRepository
from ..domain.events import (
    TaskStarted,
    TaskCompleted as TaskCompletedEvent,
    TaskFailed as TaskFailedEvent,
    TaskDeleted as TaskDeletedEvent,
    ProductSavedFromCollect,
)
from ..facade import CollectFacade

logger = logging.getLogger(__name__)


class CollectApplicationService(CollectFacade):
    """Collect 域应用服务 — 实现 CollectFacade，编排领域对象和仓储。"""

    def __init__(
        self,
        task_repo: CollectTaskRepository,
        settings_facade,   # SettingsFacade
        event_bus: EventBus,
        data_root: str,
    ):
        self._task_repo = task_repo
        self._settings_facade = settings_facade
        self._event_bus = event_bus
        self._data_root = data_root

    # ==================== 任务管理 ====================

    def list_tasks(self) -> list[dict]:
        completed = self._task_repo.list_completed()
        return [t.to_api() for t in completed]

    def start(self, url: str, platform: str = "") -> dict:
        if not url.startswith(("http://", "https://")):
            return {"error": "请输入有效的网址（以 http:// 或 https:// 开头）"}

        if not platform:
            platform = UrlService.extract_platform(url)

        tid = TaskId.generate(prefix="collect")
        task = CollectTask(
            id=tid.value,
            url=url,
            platform=platform,
        )
        task.start(platform=platform)
        self._task_repo.save(task)

        self._event_bus.publish(TaskStarted(task_id=task.id, url=url))

        thread = threading.Thread(
            target=self._run_collect_pipeline,
            args=(url, task.id),
            daemon=True,
        )
        thread.start()

        return {
            "task_id": task.id,
            "status": "pending",
            "message": "任务已创建，正在启动...",
        }

    def get_status(self, task_id: str) -> dict:
        task = self._task_repo.find_by_id(task_id)
        if not task:
            return {"error": "任务不存在"}
        return task.to_status()

    def get_result(self, task_id: str) -> dict:
        task = self._task_repo.find_by_id(task_id)
        if not task:
            return {"error": "任务不存在"}

        if task.status != "completed":
            return {"error": "任务尚未完成", "status": task.status}

        return self._build_task_result(task)

    def delete_task(self, task_id: str):
        task = self._task_repo.find_by_id(task_id)
        if not task:
            return {"error": "任务不存在"}

        self._task_repo.delete(task_id)

        import shutil
        folder = os.path.join(self._data_root, f"collect_{task_id}")
        if os.path.exists(folder):
            shutil.rmtree(folder)

        self._event_bus.publish(TaskDeletedEvent(task_id=task_id))

        return {"success": True, "task_id": task_id, "message": "采集任务已删除"}

    # ==================== 产品化 ====================

    def get_product_status(self, task_id: str) -> dict:
        """查询采集任务是否已转为产品"""
        products_data = self._load_products_file()
        product_list = products_data.get("产品列表", [])
        for p in product_list:
            if p.get("source_task_id") == task_id:
                return {
                    "saved": True,
                    "skc": p.get("skc", ""),
                    "skus": p.get("skus", []),
                    "category": p.get("category", ""),
                    "title": p.get("title", ""),
                }
        return {"saved": False}

    def save_to_product(self, task_id: str) -> dict:
        task = self._task_repo.find_by_id(task_id)
        if not task:
            return {"error": "任务不存在"}

        if not task.is_completed:
            return {"error": "任务尚未完成", "status": task.status}

        # 检查是否已保存
        status = self.get_product_status(task_id)
        if status.get("saved"):
            return {"error": "该产品已保存", "skc": status["skc"]}

        result = task.result
        title = result.get("title", "未命名产品")
        product_data = self._load_json_file(result.get("product_data", ""))

        # 生成 SKC
        category_cn = CategorizationService.guess_category(title)
        category_code = CATEGORY_CODES.get(category_cn, "OTHR")

        products_data = self._load_products_file()
        registered = products_data.get("已注册编号", {})

        max_num = 0
        for skc in registered.keys():
            if skc.startswith(category_code + "-"):
                try:
                    num = int(skc.split("-")[1])
                    if num > max_num:
                        max_num = num
                except:
                    pass

        new_num = max_num + 1
        skc = f"{category_code}-{new_num:04d}"
        while skc in registered:
            new_num += 1
            skc = f"{category_code}-{new_num:04d}"

        # 生成 SKU
        images_mapping = self._load_json_file(result.get("images_mapping"))
        skus = []
        if isinstance(images_mapping, dict):
            for i, variant_name in enumerate(sorted(images_mapping.keys())):
                sku = CategorizationService.generate_sku(skc, variant_name, i + 1)
                skus.append(sku)
        elif isinstance(images_mapping, list) and len(images_mapping) > 0:
            skus.append(f"{skc}-01")

        if not skus:
            skus.append(f"{skc}-DEFAULT")

        # 找缩略图
        thumbnail = self._find_thumbnail(result, skc)

        # 创建产品
        from datetime import datetime
        product_entry = {
            "skc": skc,
            "skus": skus,
            "title": title,
            "category": category_cn,
            "category_code": category_code,
            "source_task_id": task_id,
            "source_url": result.get("url", ""),
            "platform": result.get("platform", ""),
            "price": result.get("price", ""),
            "created_at": datetime.now().isoformat(),
            "product_data": product_data,
            "images_dir": result.get("images_dir", ""),
            "thumbnail": thumbnail,
            "downloaded": result.get("downloaded", 0),
            "image_count": result.get("image_count", 0),
        }

        products_data["已注册编号"][skc] = title
        products_data.setdefault("产品列表", []).append(product_entry)
        self._save_products_file(products_data)

        self._event_bus.publish(ProductSavedFromCollect(task_id=task_id, skc=skc))
        return {
            "success": True,
            "skc": skc,
            "skus": skus,
            "category": category_cn,
            "message": f"产品已保存为 {skc}",
        }

    # ==================== 各平台采集入口 ====================

    def capture_amazon(self, url: str, html: str, settings: dict) -> dict:
        """Amazon 浏览器扩展捕获"""
        import uuid as uuid_lib
        from ..infrastructure.capture_engine import CaptureEngine

        return CaptureEngine.amazon_capture(
            html=html,
            settings=settings,
            task_repo=self._task_repo,
            event_bus=self._event_bus,
            data_root=self._data_root,
            settings_facade=self._settings_facade,
        )

    def capture_browser(self, html: str, url: str) -> dict:
        """通用浏览器捕获"""
        import uuid as uuid_lib
        from ..infrastructure.capture_engine import CaptureEngine

        return CaptureEngine.browser_capture(
            html=html,
            url=url,
            task_repo=self._task_repo,
            event_bus=self._event_bus,
            data_root=self._data_root,
            settings_facade=self._settings_facade,
        )

    def capture_dxm(self, data: dict, store_id: str) -> dict:
        """店小秘捕获"""
        from ..infrastructure.capture_engine import CaptureEngine

        return CaptureEngine.dxm_capture(
            data=data,
            store_id=store_id,
            task_repo=self._task_repo,
            event_bus=self._event_bus,
            data_root=self._data_root,
            run_collect_in_thread=self._run_collect_pipeline,
        )

    def save_html(self, html: str, url: str) -> dict:
        """保存 HTML 快照"""
        from ..infrastructure.capture_engine import CaptureEngine

        return CaptureEngine.save_html(html=html, url=url, data_root=self._data_root)

    # ==================== 内部辅助 ====================

    def _run_collect_pipeline(self, url: str, task_id: str):
        """在后台线程中执行采集流水线"""
        from ..infrastructure.collection_engine import CollectionEngine

        engine = CollectionEngine(
            settings_facade=self._settings_facade,
            data_root=self._data_root,
        )

        task = self._task_repo.find_by_id(task_id)
        if task:
            task.update_progress("pending", 0, "等待开始...")
            self._task_repo.save(task)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                engine.run_pipeline(url, task_id, self._on_progress)
            )
            loop.close()

            task = self._task_repo.find_by_id(task_id)
            if task:
                task.complete(result)
                self._task_repo.save(task)
                self._task_repo.save_all()
                self._event_bus.publish(TaskCompletedEvent(
                    task_id=task_id,
                    platform=result.get("platform", ""),
                    title=result.get("title", ""),
                ))
        except Exception as e:
            logger.error("[%s] 采集失败: %s", task_id, e)
            task = self._task_repo.find_by_id(task_id)
            if task:
                task.fail(str(e))
                self._task_repo.save(task)
                self._task_repo.save_all()
                self._event_bus.publish(TaskFailedEvent(task_id=task_id, error=str(e)))

    def _on_progress(self, task_id: str, status: str, progress: int, message: str):
        """进度回调"""
        task = self._task_repo.find_by_id(task_id)
        if task:
            task.update_progress(status, progress, message)

    def _build_task_result(self, task: CollectTask) -> dict:
        """构建完整的任务结果（含产品数据、图片映射、缩略图 URL）"""
        result = task.result
        base_url = f"/collect_images/{task.id}"

        product_data = self._load_json_file(result.get("product_data", ""))
        images_mapping = self._load_json_file(result.get("images_mapping"))

        thumbnail_urls = []
        variant_groups = {}
        images_dir = result.get("images_dir", "")

        if images_dir and os.path.isdir(images_dir):
            # 查找子目录（变体结构: images/01_Name/）
            try:
                subdirs = sorted([
                    d for d in os.listdir(images_dir)
                    if os.path.isdir(os.path.join(images_dir, d))
                ])
                for sd in subdirs:
                    sd_path = os.path.join(images_dir, sd)
                    files = sorted([
                        f for f in os.listdir(sd_path)
                        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                    ])
                    if files:
                        variant_name = sd.split("_", 1)[-1] if "_" in sd else sd
                        variant_groups[variant_name] = len(files)
                        for f in files[:6]:
                            rel_path = os.path.relpath(os.path.join(sd_path, f), os.path.dirname(images_dir))
                            thumbnail_urls.append(f"{base_url}/{rel_path.replace(os.sep, '/')}")
            except Exception:
                pass

            if not thumbnail_urls:
                try:
                    files = sorted([
                        f for f in os.listdir(images_dir)
                        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                    ])[:12]
                    for f in files:
                        thumbnail_urls.append(f"{base_url}/images/{f}")
                except Exception:
                    pass

        return {
            "task_id": task.id,
            "summary": result,
            "product_data": product_data,
            "images_mapping": images_mapping,
            "thumbnail_urls": thumbnail_urls,
            "variant_groups": variant_groups,
        }

    def _load_json_file(self, path: str):
        """安全加载 JSON 文件"""
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        if isinstance(path, dict):
            return path
        if isinstance(path, list):
            return path
        return {} if not path else []

    def _load_products_file(self) -> dict:
        """加载 products.json"""
        filepath = os.path.join(self._data_root, "products.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"已注册编号": {}, "产品列表": []}

    def _save_products_file(self, data: dict):
        """保存 products.json"""
        filepath = os.path.join(self._data_root, "products.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _find_thumbnail(self, result: dict, skc: str) -> str:
        images_dir = result.get("images_dir", "")
        if images_dir and os.path.exists(images_dir):
            valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
            for root, _dirs, files in os.walk(images_dir):
                for fname in sorted(files):
                    if os.path.splitext(fname)[1].lower() in valid_exts:
                        rel = os.path.relpath(os.path.join(root, fname), images_dir)
                        return f"/product_images/{skc}/{rel.replace(os.sep, '/')}"
        return ""
