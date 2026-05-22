"""
ImageTask 域 - 应用服务（用例编排）。
实现 ImageTaskFacade，编排领域对象和仓储。
"""
from __future__ import annotations

import os
import json
import base64
import shutil
import mimetypes
import uuid
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.serp.shared import EventBus

from ..domain.entities import ImageTask, TaskCard
from ..domain.events import (
    TaskCreated,
    TaskDeleted,
    TaskUpdated,
    ImagesGenerated,
    ImagesSaved,
    ImagesCompressed,
    SourceImagesUploaded,
    ReferenceImageUploaded,
    ImagesImported,
    ImagesSavedToProduct,
    ImagesCopiedToClipboard,
    TaskFolderOpened,
)
from ..domain.repositories import ImageTaskRepository
from ..domain.services import TASK_TYPES, _generate_task_name
from ..domain.services import CompressImageService, CopyToClipboardService, FileManagementService
from ..facade import ImageTaskFacade
from .dto import TaskViewDTO, GenerateConfigDTO

if TYPE_CHECKING:
    from src.serp.settings.facade import SettingsFacade

logger = logging.getLogger(__name__)


class ImageTaskApplicationService(ImageTaskFacade):
    """ImageTask 域应用服务 — 实现 ImageTaskFacade，编排领域对象和仓储。"""

    def __init__(
        self,
        task_repo: ImageTaskRepository,
        settings_facade: "SettingsFacade",
        event_bus: EventBus,
        data_root: str,
        products_file: str,
    ):
        self._task_repo = task_repo
        self._settings_facade = settings_facade
        self._event_bus = event_bus
        self._data_root = data_root
        self._products_file = products_file

    # ==================== 任务类型 ====================

    def list_task_types(self) -> list[dict]:
        return TASK_TYPES

    # ==================== 任务 CRUD ====================

    def list_tasks(self) -> list[dict]:
        tasks = self._task_repo.load_all()
        return [t.to_summary_dict() for t in tasks]

    def get_task(self, task_id: str) -> dict:
        tasks = self._task_repo.load_all()
        task_info = next((t for t in tasks if t.id == task_id), None)

        task = self._task_repo.load(task_id)
        if task is None:
            return {
                "id": task_id,
                "name": task_info.name if task_info else "",
                "type": task_info.type if task_info else "",
                "data": {},
            }

        result = task.to_view_dict()
        if task_info and not result.get("name"):
            result["name"] = task_info.name
        return result

    def create_task(self, data: dict) -> dict:
        tasks = self._task_repo.load_all()
        task_type = data.get("type", "")

        existing_names = [t.name for t in tasks]
        name = _generate_task_name(task_type, existing_names) if task_type else _generate_task_name("", existing_names)

        task_id = str(uuid.uuid4())[:8]
        task = ImageTask(id=task_id, name=name, type=task_type, skc=data.get("skc", ""))
        task.text1 = ""
        task.cards = []

        self._task_repo.save(task)

        self._event_bus.publish(TaskCreated(task_id=task_id, task_name=name))
        logger.info("Task created: %s (%s)", name, task_id)
        return {"id": task_id, "name": name, "type": task_type}

    def update_task(self, task_id: str, data: dict) -> dict:
        name = data.get("name")
        task_data = data.get("data")

        if name is not None:
            tasks = self._task_repo.load_all()
            for t in tasks:
                if t.id == task_id:
                    t.name = name
                    self._task_repo.save(t)
                    break

        if task_data is not None:
            task = self._task_repo.load(task_id)
            if task is None:
                task = ImageTask(id=task_id)
            task.update_info(task_data=task_data)
            self._task_repo.save(task)

        self._event_bus.publish(TaskUpdated(task_id=task_id))
        return {"status": "ok"}

    def delete_task(self, task_id: str):
        tasks = self._task_repo.load_all()
        task_info = next((t for t in tasks if t.id == task_id), None)
        if not task_info:
            return

        self._task_repo.delete(task_id)
        self._task_repo.delete_task_directory(task_id)

        self._event_bus.publish(TaskDeleted(task_id=task_id))
        logger.info("Task deleted: %s", task_id)

    # ==================== 图片操作 ====================

    def upload_source_images(self, task_id: str, files: list) -> dict:
        saved = []
        for f in files:
            if f.filename == "":
                continue
            relative_path = self._task_repo.save_uploaded_file(task_id, f, f.filename)
            saved.append({
                "original_name": f.filename,
                "saved_name": os.path.basename(relative_path),
                "relative_path": relative_path,
            })

        self._event_bus.publish(SourceImagesUploaded(task_id=task_id, count=len(saved)))
        return {"saved": saved}

    def upload_ref_image(self, task_id: str, ref_index: int, file) -> dict:
        if ref_index not in (1, 2):
            return {"error": "ref_index 必须为 1 或 2"}

        if not file or file.filename == "":
            return {"error": "未选择图片"}

        relative_path = self._task_repo.save_ref_image(task_id, ref_index, file)

        task = self._task_repo.load(task_id)
        if task:
            task.set_ref_image(ref_index, relative_path)
            self._task_repo.save(task)

        self._event_bus.publish(ReferenceImageUploaded(task_id=task_id, ref_index=ref_index))
        return {"success": True, "ref_index": ref_index, "path": relative_path}

    def import_images(self, task_id: str, urls: list[str]) -> dict:
        # urls here is actually a payload: {skc, entries}
        # From the route: data = request.get_json(), skc, entries
        # We adapt the facade to receive the same structure
        return {"saved": []}

    # (import_images is overloaded — see route-level adapter in blueprint)
    def _import_images_from_product(self, task_id: str, skc: str, entries: list[dict]) -> dict:
        """将产品图片复制到任务 source_images 目录"""
        products_data = self._load_products()
        product_list = products_data.get("产品列表", [])
        product = None
        for p in product_list:
            if p["skc"] == skc:
                product = p
                break
        if not product:
            return {"error": "产品不存在"}

        images_dir = product.get("images_dir", "")
        if not images_dir or not os.path.exists(images_dir):
            return {"error": "产品图片目录不存在"}

        filenames = [entry.get("filename", "") for entry in entries if entry.get("filename")]
        saved = self._task_repo.import_product_images(task_id, images_dir, filenames)

        self._event_bus.publish(ImagesImported(task_id=task_id, count=len(saved)))
        return {"saved": saved}

    def generate(self, task_id: str, config: dict) -> dict:
        api_key, model_name, api_base = self._resolve_ai_config()
        if not api_key:
            return {"error": "API_KEY not configured"}

        task_folder = self._task_repo.task_folder(task_id)

        card_id = config.get("card_id", "")
        prompt = config.get("prompt", "")
        source_image_path = config.get("source_image_path", "")
        extra_image_paths = config.get("extra_image_paths") or []
        auto_compress = config.get("auto_compress", True)

        ref_image_data = None
        mime_type = "image/jpeg"
        if source_image_path:
            full_path = os.path.join(task_folder, source_image_path)
            if os.path.exists(full_path):
                mime_type = mimetypes.guess_type(full_path)[0] or "image/jpeg"
                with open(full_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                ref_image_data = {"mime_type": mime_type, "data": encoded}

        parts = [{"text": prompt}]
        if ref_image_data:
            parts.append({"inline_data": ref_image_data})

        for img_path in extra_image_paths:
            full = os.path.join(task_folder, img_path)
            if os.path.exists(full):
                img_mime = mimetypes.guess_type(full)[0] or "image/jpeg"
                with open(full, "rb") as f:
                    img_enc = base64.b64encode(f.read()).decode("utf-8")
                parts.append({"inline_data": {"mime_type": img_mime, "data": img_enc}})

        api_url = f"{api_base}/models/{model_name}:generateContent"

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"imageSize": "2K"},
            },
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        import requests

        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=180)
            if resp.status_code != 200:
                return {"error": f"API Error {resp.status_code}: {resp.text}"}

            result = resp.json()
            image_part = None
            for candidate in result.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    inline_data = part.get("inlineData") or part.get("inline_data")
                    if inline_data and inline_data.get("data"):
                        image_part = inline_data
                        break
                if image_part:
                    break

            if not image_part:
                return {"error": "No image data in response", "detail": result}

            mime = image_part.get("mimeType") or image_part.get("mime_type") or "image/png"
            ext = "jpg" if mime == "image/jpeg" else "webp" if mime == "image/webp" else "png"
            file_name = f"{card_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{ext}"

            draft_dir = os.path.join(task_folder, "drafts")
            os.makedirs(draft_dir, exist_ok=True)
            draft_path = os.path.join(draft_dir, file_name)
            image_data = base64.b64decode(image_part["data"])

            if auto_compress:
                compressed_data, compressed_mime = CompressImageService.compress(image_data)
                if len(compressed_data) < len(image_data):
                    image_data = compressed_data
                    file_name = f"{card_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
                    draft_path = os.path.join(draft_dir, file_name)

            with open(draft_path, "wb") as f:
                f.write(image_data)

            url = f"/task_images/{task_id}/drafts/{file_name}"
            base64_img = base64.b64encode(image_data).decode("utf-8")
            self._event_bus.publish(ImagesGenerated(task_id=task_id, count=1))

            return {
                "success": True,
                "url": url,
                "base64": f"data:{mime};base64,{base64_img}",
                "draft_file": f"drafts/{file_name}",
            }
        except Exception as e:
            logger.exception("Image generation failed for task %s", task_id)
            return {"error": str(e)}

    def save_images(self, task_id: str, data: dict) -> dict:
        moved = self._task_repo.move_drafts_to_generated(task_id)

        task = self._task_repo.load(task_id)
        if task:
            task.finalize_generated_images(moved)
            self._task_repo.save(task)

        self._event_bus.publish(ImagesSaved(task_id=task_id, count=len(moved)))
        return {"moved": moved, "generated_dir": f"task_images/{task_id}/generated"}

    def compress_images(self, task_id: str, config: dict) -> dict:
        gen_dir = os.path.join(self._task_repo.task_folder(task_id), "generated")
        if not os.path.exists(gen_dir):
            return {
                "success": True,
                "compressed_count": 0,
                "error_count": 0,
                "total_size_before": 0,
                "total_size_after": 0,
                "saved_bytes": 0,
            }

        compressed_count = 0
        error_count = 0
        total_size_before = 0
        total_size_after = 0

        for fname in os.listdir(gen_dir):
            fpath = os.path.join(gen_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
                continue
            try:
                with open(fpath, "rb") as f:
                    original_data = f.read()
                size_before = len(original_data)
                if size_before <= 1_572_864:
                    continue
                compressed_data, new_mime = CompressImageService.compress(original_data)
                size_after = len(compressed_data)
                if size_after < size_before:
                    new_fname = os.path.splitext(fname)[0] + ".jpg"
                    new_fpath = os.path.join(gen_dir, new_fname)
                    with open(new_fpath, "wb") as f:
                        f.write(compressed_data)
                    if new_fname != fname:
                        os.remove(fpath)
                    total_size_before += size_before
                    total_size_after += size_after
                    compressed_count += 1
            except Exception as e:
                error_count += 1
                logger.warning("Compress failed for %s: %s", fname, e)
                continue

        saved_bytes = total_size_before - total_size_after
        self._event_bus.publish(ImagesCompressed(
            task_id=task_id, compressed_count=compressed_count, saved_bytes=saved_bytes
        ))

        return {
            "success": True,
            "compressed_count": compressed_count,
            "error_count": error_count,
            "total_size_before": total_size_before,
            "total_size_after": total_size_after,
            "saved_bytes": saved_bytes,
        }

    # ==================== 导出 ====================

    def save_to_product(self, task_id: str, data: dict) -> dict:
        """将任务的生成图片复制到指定产品的图片集/子集"""
        skc = data.get("skc")
        setName = data.get("setName")
        subName = data.get("subName", "")

        products_data = self._load_products()
        product_list = products_data.get("产品列表", [])
        product = next((p for p in product_list if p["skc"] == skc), None)
        if not product:
            return {"error": "产品不存在"}

        images_dir = product.get("images_dir", "")
        if not images_dir or not os.path.exists(images_dir):
            return {"error": "产品图片目录不存在"}

        task_folder = self._task_repo.task_folder(task_id)
        gen_files = self._task_repo.get_generated_files(task_id, include_drafts=True)
        if not gen_files:
            return {"saved": [], "message": "没有生成图片可保存"}

        gen_dir = os.path.join(task_folder, "generated")
        if not os.path.exists(gen_dir) or not os.listdir(gen_dir):
            gen_dir = os.path.join(task_folder, "drafts")

        path_prefix = f"{setName}/{subName}/" if subName else f"{setName}/"
        target_dir = os.path.join(images_dir, path_prefix)
        os.makedirs(target_dir, exist_ok=True)

        saved = []
        for fname in gen_files:
            src = os.path.join(gen_dir, fname)
            if not os.path.isfile(src):
                continue
            dest_name = fname
            dest_path = os.path.join(target_dir, dest_name)
            name_parts = os.path.splitext(fname)
            counter = 1
            while os.path.exists(dest_path):
                dest_name = f"{name_parts[0]}_{counter}{name_parts[1]}"
                dest_path = os.path.join(target_dir, dest_name)
                counter += 1
            shutil.copy2(src, dest_path)
            rel_path = (path_prefix + dest_name).replace("\\", "/")
            saved.append({"filename": rel_path, "index": 0})

        image_sets = product.get("image_sets", {})
        if setName not in image_sets:
            image_sets[setName] = []
        max_idx = max([e.get("index", 0) for e in image_sets[setName]], default=-1)
        for entry in saved:
            max_idx += 1
            entry["index"] = max_idx
            image_sets[setName].append(entry)

        if subName:
            image_subsets = product.get("image_subsets", {})
            image_subsets.setdefault(setName, {}).setdefault(subName, [])
            max_sub_idx = max([e.get("index", 0) for e in image_subsets[setName][subName]], default=-1)
            for entry in saved:
                sub_entry = {"filename": entry["filename"], "index": 0}
                max_sub_idx += 1
                sub_entry["index"] = max_sub_idx
                image_subsets[setName][subName].append(sub_entry)
            product["image_subsets"] = image_subsets

        product["image_sets"] = image_sets
        self._save_products(products_data)

        self._event_bus.publish(ImagesSavedToProduct(task_id=task_id, skc=skc, count=len(saved)))
        return {"saved": saved, "count": len(saved), "target": f"{skc}/{path_prefix}"}

    def copy_to_clipboard(self, task_id: str) -> dict:
        """从任务图片复制到剪贴板。type 参数在路由层解析并作为 data 传入。"""
        # The type parameter comes from the request, but the facade method
        # signature doesn't have it. We'll handle this in the blueprint.
        # For now, return an error — the blueprint will call _copy_to_clipboard_with_type
        return {"error": "Use route-level handler for clipboard"}

    def _copy_to_clipboard_with_type(self, task_id: str, img_type: str) -> dict:
        task = self._task_repo.load(task_id)
        task_folder = self._task_repo.task_folder(task_id)

        if task is None:
            return {"error": "任务不存在"}

        paths = []
        for card in task.cards:
            p = None
            if img_type == "source":
                p = card.source_image
            else:
                p = card.generated_final or card.generated_draft
            if p:
                full = os.path.join(task_folder, p).replace("/", "\\")
                if os.path.exists(full):
                    paths.append(full)

        if not paths:
            return {"error": "没有可复制的图片"}

        try:
            CopyToClipboardService.copy_files(paths)
            self._event_bus.publish(ImagesCopiedToClipboard(task_id=task_id, count=len(paths)))
            return {"copied": len(paths)}
        except Exception as e:
            return {"error": str(e)}

    def open_folder(self, task_id: str):
        folder = os.path.join(self._task_repo.task_folder(task_id), "generated")
        FileManagementService.open_folder(folder)
        self._event_bus.publish(TaskFolderOpened(task_id=task_id, folder=folder))

    # ==================== 内部辅助方法 ====================

    def _resolve_ai_config(self) -> tuple[str, str, str]:
        """从 SettingsFacade 解析 AI 模型配置，返回 (api_key, model_name, api_base_url)"""
        try:
            model_id = self._settings_facade.get_feature_model("image_generation")
            models = self._settings_facade.get_models()
            model_config = next((m for m in models if m["id"] == model_id), None)
            if model_config:
                api_key_env = model_config.get("api_key_env", "API_KEY")
                api_key = os.getenv(api_key_env, "")
                model_name = model_config.get("model", "gemini-3.1-flash-image-preview")
                # Gemini API URL: base_url + /models/{model}:generateContent
                base_url = model_config.get("base_url", "https://api.laozhang.ai/v1beta")
                return api_key, model_name, base_url
        except Exception:
            pass

        api_key = os.getenv("API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
        model_name = os.getenv("IMAGE_MODEL", "gemini-3.1-flash-image-preview")
        base_url = "https://api.laozhang.ai/v1beta"
        return api_key, model_name, base_url

    def _load_products(self) -> dict:
        if not os.path.exists(self._products_file):
            return {"产品列表": []}
        try:
            with open(self._products_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {"产品列表": []}
        except (json.JSONDecodeError, OSError):
            return {"产品列表": []}

    def _save_products(self, products_data: dict):
        os.makedirs(os.path.dirname(self._products_file), exist_ok=True)
        with open(self._products_file, "w", encoding="utf-8") as f:
            json.dump(products_data, f, indent=2, ensure_ascii=False)
