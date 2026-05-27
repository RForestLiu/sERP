"""
JsonFileStore — 原子 JSON 文件读写工具。
"""
import json
import os
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class JsonFileStore:
    """JSON 文件存储工具 — 读/写/备份，不关心业务类型。

    用法:
        store = JsonFileStore("data/settings.json")
        data = store.read()
        store.write({"key": "value"})
    """

    def __init__(self, filepath: str, backup: bool = True):
        self._filepath = Path(filepath)
        self._backup = backup

    @property
    def path(self) -> Path:
        return self._filepath

    def exists(self) -> bool:
        return self._filepath.exists()

    def read(self) -> Optional[dict]:
        """读取 JSON 文件，不存在或损坏返回 None"""
        if not self._filepath.exists():
            return None
        try:
            with open(self._filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", self._filepath, e)
            return None

    def read_list(self) -> Optional[list]:
        """读取 JSON 数组文件"""
        if not self._filepath.exists():
            return None
        try:
            with open(self._filepath, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return data if isinstance(data, list) else None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", self._filepath, e)
            return None

    def read_any(self):
        """读取任意 JSON 内容"""
        if not self._filepath.exists():
            return None
        try:
            with open(self._filepath, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", self._filepath, e)
            return None

    def write(self, data: dict):
        """原子写入 JSON 对象（先写临时文件，再替换）"""
        self._ensure_dir()
        if self._backup and self._filepath.exists():
            self._backup_file()
        tmp = self._filepath.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._filepath)
        except Exception as e:
            logger.error("Failed to write %s: %s", self._filepath, e)
            if tmp.exists():
                tmp.unlink()
            raise

    def write_list(self, data: list):
        """原子写入 JSON 数组"""
        self._ensure_dir()
        if self._backup and self._filepath.exists():
            self._backup_file()
        tmp = self._filepath.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._filepath)
        except Exception as e:
            logger.error("Failed to write %s: %s", self._filepath, e)
            if tmp.exists():
                tmp.unlink()
            raise

    def _ensure_dir(self):
        self._filepath.parent.mkdir(parents=True, exist_ok=True)

    def _backup_file(self):
        backup = self._filepath.with_suffix(".json.bak")
        try:
            shutil.copy2(self._filepath, backup)
        except OSError:
            pass
