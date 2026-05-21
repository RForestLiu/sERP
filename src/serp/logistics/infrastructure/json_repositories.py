"""
Logistics 域 - JSON 文件仓储实现。
"""
import json
import os
import logging
from typing import Optional

from ..domain.entities import LogisticsTemplate
from ..domain.repositories import LogisticsTemplateRepository

logger = logging.getLogger(__name__)


class JsonLogisticsTemplateRepository(LogisticsTemplateRepository):
    """JSON 文件物流模板仓储 — 从目录读取 .json 模板文件"""

    def __init__(self, templates_dir: str):
        self._dir = templates_dir

    def load_all(self) -> list[LogisticsTemplate]:
        templates = []
        if not os.path.isdir(self._dir):
            return templates
        for fname in os.listdir(self._dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._dir, fname)
            data = self._read_file(path)
            if data:
                templates.append(LogisticsTemplate.from_dict(data))
        return templates

    def find_by_id(self, template_id: str) -> Optional[LogisticsTemplate]:
        if not os.path.isdir(self._dir):
            return None
        for fname in os.listdir(self._dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(self._dir, fname)
            data = self._read_file(path)
            if data and data.get("id") == template_id:
                return LogisticsTemplate.from_dict(data)
        return None

    @staticmethod
    def _read_file(path: str) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error("Failed to load logistics template: %s — %s", path, e)
            return None
