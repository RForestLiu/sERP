"""
ImageTask 域 - JSON 文件仓储实现。
"""
from __future__ import annotations

import os
import json
import shutil
import uuid
import logging
from datetime import datetime
from typing import Optional

from src.serp.shared import JsonFileStore

from ..domain.entities import ImageTask
from ..domain.repositories import ImageTaskRepository
from ..domain.services import FileManagementService

logger = logging.getLogger(__name__)


class JsonImageTaskRepository(ImageTaskRepository):
    """JSON 文件图片任务仓储"""

    def __init__(self, tasks_filepath: str, data_root: str):
        self._tasks_store = JsonFileStore(tasks_filepath)
        self._data_root = data_root

    # ── 任务列表 CRUD ──

    def load_all(self) -> list[ImageTask]:
        data = self._tasks_store.read_list()
        if data is None:
            return []
        return [
            ImageTask.from_summary_dict(
                item, self._load_task_data(item.get("id", ""))
            )
            for item in data
            if isinstance(item, dict)
        ]

    def save_all(self, tasks: list[ImageTask]):
        summaries = [t.to_summary_dict() for t in tasks]
        self._tasks_store.write_list(summaries)
        for task in tasks:
            self._save_task_data(task.id, task.to_task_data_dict())

    def save(self, entity: ImageTask):
        # Save summary to tasks.json
        summaries = self._tasks_store.read_list() or []
        found = False
        for i, item in enumerate(summaries):
            if isinstance(item, dict) and item.get("id") == entity.id:
                summaries[i] = entity.to_summary_dict()
                found = True
                break
        if not found:
            summaries.append(entity.to_summary_dict())
        self._tasks_store.write_list(summaries)

        # Save task data
        self._save_task_data(entity.id, entity.to_task_data_dict())

    def delete(self, task_id: str):
        summaries = self._tasks_store.read_list() or []
        summaries = [s for s in summaries if not (isinstance(s, dict) and s.get("id") == task_id)]
        self._tasks_store.write_list(summaries)

    def load(self, task_id: str) -> Optional[ImageTask]:
        summaries = self._tasks_store.read_list() or []
        summary = None
        for item in summaries:
            if isinstance(item, dict) and item.get("id") == task_id:
                summary = item
                break
        if summary is None:
            return None
        task_data = self._load_task_data(task_id)
        return ImageTask.from_summary_dict(summary, task_data)

    # ── 文件管理 ──

    def ensure_dirs(self, task_id: str):
        FileManagementService.ensure_task_dirs(self._data_root, task_id)

    def delete_task_directory(self, task_id: str):
        task_dir = FileManagementService.task_folder(self._data_root, task_id)
        task_data_file = os.path.join(task_dir, "task_data.json")
        if os.path.exists(task_data_file):
            os.remove(task_data_file)
        if os.path.exists(task_dir):
            try:
                shutil.rmtree(task_dir)
            except Exception:
                pass

    def task_folder(self, task_id: str) -> str:
        return FileManagementService.task_folder(self._data_root, task_id)

    def get_generated_files(self, task_id: str, include_drafts: bool = False) -> list[str]:
        """获取生成图片文件列表"""
        task_dir = self.task_folder(task_id)
        gen_dir = os.path.join(task_dir, "generated")
        gen_files = []
        if os.path.exists(gen_dir):
            gen_files = sorted([
                f for f in os.listdir(gen_dir)
                if os.path.isfile(os.path.join(gen_dir, f))
            ])

        if not gen_files and include_drafts:
            drafts_dir = os.path.join(task_dir, "drafts")
            if os.path.exists(drafts_dir):
                task_data = self._load_task_data(task_id)
                seen = set()
                for card in task_data.get("cards", []):
                    draft = card.get("generated_draft", "")
                    if draft:
                        fname = os.path.basename(draft)
                        fpath = os.path.join(task_dir, draft)
                        if fname not in seen and os.path.isfile(fpath):
                            seen.add(fname)
                            gen_files.append(fname)

        return gen_files

    def move_drafts_to_generated(self, task_id: str) -> list[str]:
        """把 drafts 目录中的文件移到 generated 目录，返回移动的文件名列表"""
        task_dir = self.task_folder(task_id)
        draft_dir = os.path.join(task_dir, "drafts")
        gen_dir = os.path.join(task_dir, "generated")
        os.makedirs(gen_dir, exist_ok=True)

        moved = []
        if os.path.exists(draft_dir):
            for fname in os.listdir(draft_dir):
                src = os.path.join(draft_dir, fname)
                dst = os.path.join(gen_dir, fname)
                if os.path.isfile(src):
                    shutil.move(src, dst)
                    moved.append(fname)
        return moved

    def save_uploaded_file(self, task_id: str, file_data, filename: str) -> str:
        """保存上传的文件到 source_images 目录，返回相对路径"""
        self.ensure_dirs(task_id)
        task_dir = self.task_folder(task_id)
        source_dir = os.path.join(task_dir, "source_images")
        safe_name = filename
        save_path = os.path.join(source_dir, safe_name)
        file_data.save(save_path)
        return f"source_images/{safe_name}"

    def save_ref_image(self, task_id: str, ref_index: int, file_data) -> str:
        """保存参考图，返回相对路径"""
        self.ensure_dirs(task_id)
        task_dir = self.task_folder(task_id)
        source_dir = os.path.join(task_dir, "source_images")

        # 删除旧参考图
        for name in os.listdir(source_dir):
            if name.startswith(f"_ref_{ref_index}.") or name.startswith(f"_ref_{ref_index}_"):
                old_path = os.path.join(source_dir, name)
                try:
                    if os.path.isfile(old_path):
                        os.remove(old_path)
                except Exception as e:
                    logger.warning("[上传参考图] 删除旧参考图失败: %s", e)

        ext = os.path.splitext(file_data.filename)[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            ext = ".jpg"
        safe_name = f"_ref_{ref_index}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
        save_path = os.path.join(source_dir, safe_name)
        file_data.save(save_path)

        logger.info("[上传参考图] task=%s ref=%s -> %s", task_id, ref_index, safe_name)
        return f"source_images/{safe_name}"

    def import_product_images(self, task_id: str, images_dir: str, filenames: list[str]) -> list[dict]:
        """从产品图片目录导入文件到任务 source_images 目录"""
        self.ensure_dirs(task_id)
        task_dir = self.task_folder(task_id)
        source_dir = os.path.join(task_dir, "source_images")

        saved = []
        for filename in filenames:
            if not filename:
                continue
            src_path = os.path.join(images_dir, filename)
            if not os.path.exists(src_path):
                continue
            safe_name = os.path.basename(filename)
            dest_name = safe_name
            dest_path = os.path.join(source_dir, dest_name)
            name_parts = os.path.splitext(safe_name)
            counter = 1
            while os.path.exists(dest_path):
                dest_name = f"{name_parts[0]}_{counter}{name_parts[1]}"
                dest_path = os.path.join(source_dir, dest_name)
                counter += 1
            shutil.copy2(src_path, dest_path)
            saved.append({
                "original_name": safe_name,
                "relative_path": f"source_images/{dest_name}",
            })

        return saved

    # ── 内部辅助 ──

    def _task_data_path(self, task_id: str) -> str:
        return os.path.join(self.task_folder(task_id), "task_data.json")

    def _load_task_data(self, task_id: str) -> dict:
        path = self._task_data_path(task_id)
        if not os.path.exists(path):
            return {"text1": "", "cards": [], "skc": ""}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {"text1": "", "cards": [], "skc": ""}
        except (json.JSONDecodeError, OSError):
            return {"text1": "", "cards": [], "skc": ""}

    def _save_task_data(self, task_id: str, data: dict):
        self.ensure_dirs(task_id)
        path = self._task_data_path(task_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
