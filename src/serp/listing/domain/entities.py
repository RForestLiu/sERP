"""
Listing 域 - 实体与聚合根。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.serp.shared import AggregateRoot

from .events import DraftSaved, DraftDeleted


@dataclass
class ListingDraft(AggregateRoot):
    """上架草稿聚合根 — 以 skc+store_id 为复合标识"""

    skc: str = ""
    store_id: str = ""
    _data: dict = field(default_factory=dict, repr=False)
    lifecycle: list[dict] = field(default_factory=list)
    updated_at: str = ""

    def __post_init__(self):
        if self.skc and self.store_id:
            self.id = f"{self.skc}_{self.store_id}"
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()

    # ── 属性 ──

    @property
    def data(self) -> dict:
        return dict(self._data)

    # ── 业务行为 ──

    def update(self, data: dict):
        """保存/更新草稿内容"""
        self._data = {**self._data, **data}
        self._data["skc"] = self.skc
        self._data["store_id"] = self.store_id
        self.updated_at = datetime.now().isoformat()
        self._data["updated_at"] = self.updated_at
        self.add_domain_event(DraftSaved(skc=self.skc, store_id=self.store_id))

    def mark_deleted(self):
        self.add_domain_event(DraftDeleted(skc=self.skc, store_id=self.store_id))

    def append_lifecycle_event(self, event: dict):
        """追加生命周期事件"""
        entry = {"at": datetime.now().isoformat(timespec="seconds")}
        entry.update(event)
        self.lifecycle.append(entry)
        self.lifecycle = self.lifecycle[-50:]
        self.updated_at = datetime.now().isoformat()
        self._data["lifecycle"] = self.lifecycle

    def to_dict(self) -> dict:
        result = dict(self._data)
        result.setdefault("skc", self.skc)
        result.setdefault("store_id", self.store_id)
        result["lifecycle"] = self.lifecycle
        result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_dict(cls, skc: str, store_id: str, data: dict) -> "ListingDraft":
        draft = cls(skc=skc, store_id=store_id)
        draft._data = {k: v for k, v in data.items() if k not in ("lifecycle", "updated_at")}
        lifecycle = data.get("lifecycle")
        if isinstance(lifecycle, list):
            draft.lifecycle = lifecycle
        draft.updated_at = data.get("updated_at", draft.updated_at)
        return draft
