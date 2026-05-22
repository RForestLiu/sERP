"""
ImageTask 域 - 实体与聚合根。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.serp.shared import AggregateRoot, Entity, DomainError


@dataclass
class TaskCard(Entity):
    """任务卡片（图片处理单元）"""
    source_image: str = ""
    text1: str = ""
    text2: str = ""
    text3: str = ""
    generated_draft: str = ""
    generated_final: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_image": self.source_image,
            "text1": self.text1,
            "text2": self.text2,
            "text3": self.text3,
            "generated_draft": self.generated_draft,
            "generated_final": self.generated_final,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskCard":
        return cls(
            id=data.get("id", ""),
            source_image=data.get("source_image", ""),
            text1=data.get("text1", ""),
            text2=data.get("text2", ""),
            text3=data.get("text3", ""),
            generated_draft=data.get("generated_draft", ""),
            generated_final=data.get("generated_final", ""),
        )


@dataclass
class ImageTask(AggregateRoot):
    """图片任务聚合根"""

    name: str = ""
    type: str = ""
    skc: str = ""
    created_at: str = ""
    text1: str = ""
    cards: list[TaskCard] = field(default_factory=list)
    ref_image_1: str = ""
    ref_image_2: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 业务行为 ──

    def update_info(self, name: str = "", task_data: Optional[dict] = None):
        if name:
            self.name = name
        if task_data is not None:
            if "text1" in task_data:
                self.text1 = task_data["text1"]
            if "cards" in task_data:
                self.cards = [
                    TaskCard.from_dict(c) if isinstance(c, dict) else c
                    for c in task_data["cards"]
                ]

    def set_ref_image(self, ref_index: int, path: str):
        if ref_index == 1:
            self.ref_image_1 = path
        elif ref_index == 2:
            self.ref_image_2 = path
        else:
            raise DomainError("ref_index must be 1 or 2")

    def mark_card_generated(self, card_id: str, draft_path: str):
        for card in self.cards:
            if card.id == card_id:
                card.generated_draft = draft_path
                return

    def finalize_generated_images(self, moved_files: list[str]):
        """将草稿标记为最终图片（文件从 drafts 移到 generated 后调用）"""
        for card in self.cards:
            if card.generated_draft:
                fname = card.generated_draft.split("/")[-1] if "/" in card.generated_draft else card.generated_draft
                if fname in moved_files:
                    card.generated_final = f"generated/{fname}"
                    card.generated_draft = ""

    # ── 序列化 ──

    def to_summary_dict(self) -> dict:
        """任务列表摘要（存 tasks.json）"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "created_at": self.created_at,
        }

    def to_task_data_dict(self) -> dict:
        """任务数据（存 task_data.json）"""
        return {
            "text1": self.text1,
            "cards": [c.to_dict() for c in self.cards],
            "skc": self.skc,
            "ref_image_1": self.ref_image_1,
            "ref_image_2": self.ref_image_2,
        }

    def to_view_dict(self) -> dict:
        """完整视图（API get_task 用）"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "created_at": self.created_at,
            "data": self.to_task_data_dict(),
        }

    @classmethod
    def from_summary_dict(cls, summary: dict, task_data: Optional[dict] = None) -> "ImageTask":
        task_data = task_data or {}
        cards = [
            TaskCard.from_dict(c) if isinstance(c, dict) else c
            for c in task_data.get("cards", [])
        ]
        return cls(
            id=summary.get("id", ""),
            name=summary.get("name", ""),
            type=summary.get("type", ""),
            skc=task_data.get("skc", ""),
            created_at=summary.get("created_at", ""),
            text1=task_data.get("text1", ""),
            cards=cards,
            ref_image_1=task_data.get("ref_image_1", ""),
            ref_image_2=task_data.get("ref_image_2", ""),
        )
