"""
ImageTask 域 - 应用层 DTO。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GenerateConfigDTO:
    """AI 生成图片配置 DTO"""
    task_id: str = ""
    card_id: str = ""
    prompt: str = ""
    source_image_path: str = ""
    extra_image_paths: list[str] = field(default_factory=list)
    auto_compress: bool = True


@dataclass
class TaskViewDTO:
    """任务视图 DTO"""
    task_id: str = ""
    name: str = ""
    type: str = ""
    created_at: str = ""
    data: dict = field(default_factory=dict)
