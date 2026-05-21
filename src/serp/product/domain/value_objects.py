"""
Product 域 - 值对象。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class ManualData(ValueObject):
    """产品手工登记数据"""
    weight_g: str = ""
    size_spec: str = ""
    spec: str = ""
    cost_price: str = ""
    collected_weight_g: str = ""
    collected_size_spec: str = ""
    collected_size_cm: list[float] = field(default_factory=list)
    collected_specs_source: str = ""
    collected_specs_evidence: dict = field(default_factory=dict)
    collected_specs_review: dict = field(default_factory=dict)
    collected_specs_at: str = ""

    def to_dict(self) -> dict:
        return {
            "weight_g": self.weight_g,
            "size_spec": self.size_spec,
            "spec": self.spec,
            "cost_price": self.cost_price,
            "collected_weight_g": self.collected_weight_g,
            "collected_size_spec": self.collected_size_spec,
            "collected_size_cm": self.collected_size_cm,
            "collected_specs_source": self.collected_specs_source,
            "collected_specs_evidence": self.collected_specs_evidence,
            "collected_specs_review": self.collected_specs_review,
            "collected_specs_at": self.collected_specs_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManualData":
        if not isinstance(data, dict):
            return cls()
        return cls(
            weight_g=str(data.get("weight_g", "") or ""),
            size_spec=str(data.get("size_spec", "") or ""),
            spec=str(data.get("spec", "") or ""),
            cost_price=str(data.get("cost_price", "") or ""),
            collected_weight_g=str(data.get("collected_weight_g", "") or ""),
            collected_size_spec=str(data.get("collected_size_spec", "") or ""),
            collected_size_cm=data.get("collected_size_cm", []) if isinstance(data.get("collected_size_cm"), list) else [],
            collected_specs_source=str(data.get("collected_specs_source", "") or ""),
            collected_specs_evidence=data.get("collected_specs_evidence", {}) if isinstance(data.get("collected_specs_evidence"), dict) else {},
            collected_specs_review=data.get("collected_specs_review", {}) if isinstance(data.get("collected_specs_review"), dict) else {},
            collected_specs_at=str(data.get("collected_specs_at", "") or ""),
        )

    def with_updates(self, weight_g: str = "", size_spec: str = "", spec: str = "",
                     cost_price: str = "") -> "ManualData":
        """返回更新了手工字段的新 ManualData，保留 collected_* 字段"""
        return ManualData(
            weight_g=weight_g or self.weight_g,
            size_spec=size_spec or self.size_spec,
            spec=spec or self.spec,
            cost_price=cost_price or self.cost_price,
            collected_weight_g=self.collected_weight_g,
            collected_size_spec=self.collected_size_spec,
            collected_size_cm=self.collected_size_cm,
            collected_specs_source=self.collected_specs_source,
            collected_specs_evidence=self.collected_specs_evidence,
            collected_specs_review=self.collected_specs_review,
            collected_specs_at=self.collected_specs_at,
        )

    def with_collected_specs(self, weight_g: Any, size_spec: str, size_cm: list[float],
                             evidence: dict, review: dict, source: str = "llm_structured_reviewed") -> "ManualData":
        """返回更新了采集规格的新 ManualData"""
        return ManualData(
            weight_g=self.weight_g,
            size_spec=self.size_spec,
            spec=self.spec,
            cost_price=self.cost_price,
            collected_weight_g=str(weight_g) if weight_g else "",
            collected_size_spec=size_spec,
            collected_size_cm=size_cm,
            collected_specs_source=source,
            collected_specs_evidence=evidence,
            collected_specs_review=review,
            collected_specs_at=datetime.now().isoformat(),
        )

    def effective_weight_g(self) -> str:
        """有效重量：手工优先 -> 采集回退"""
        return self.weight_g or self.collected_weight_g

    def effective_size_spec(self) -> str:
        """有效尺寸：手工优先 -> 采集回退"""
        return self.size_spec or self.collected_size_spec


@dataclass(frozen=True)
class StoreStatusEntry(ValueObject):
    """单店铺上架状态"""
    store_id: str
    status: str = "未上架"

    VALID_STATUSES = ("未上架", "待发布", "审核中", "已上架", "审核拒绝", "下架回归中")

    @classmethod
    def is_valid_status(cls, status: str) -> bool:
        return status in cls.VALID_STATUSES


@dataclass(frozen=True)
class ImageRef(ValueObject):
    """图片引用"""
    source: str = "local"
    url: str = ""
    local_path: str = ""
    order: int = 0

    def to_dict(self) -> dict:
        d = {"source": self.source, "url": self.url, "order": self.order}
        if self.local_path:
            d["local_path"] = self.local_path
        return d


@dataclass(frozen=True)
class ImageSetEntry(ValueObject):
    """图片集条目"""
    filename: str = ""
    url: str = ""
    index: int = 0

    def to_dict(self) -> dict:
        d = {"index": self.index}
        if self.filename:
            d["filename"] = self.filename
        if self.url:
            d["url"] = self.url
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "ImageSetEntry":
        return cls(
            filename=data.get("filename", "") or "",
            url=data.get("url", "") or "",
            index=data.get("index", 0),
        )


@dataclass(frozen=True)
class PendingApproval(ValueObject):
    """关键属性待审批记录"""
    approval_id: str = ""
    field_name: str = ""
    old_value: Any = None
    proposed_value: Any = None
    requested_by: str = ""
    requested_at: str = ""
    status: str = "pending"  # pending | approved | rejected
    approved_by: str = ""
    approved_at: str = ""
    reject_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "approval_id": self.approval_id,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "proposed_value": self.proposed_value,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "reject_reason": self.reject_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingApproval":
        if not isinstance(data, dict):
            return cls()
        return cls(
            approval_id=str(data.get("approval_id", "") or ""),
            field_name=str(data.get("field_name", "") or ""),
            old_value=data.get("old_value"),
            proposed_value=data.get("proposed_value"),
            requested_by=str(data.get("requested_by", "") or ""),
            requested_at=str(data.get("requested_at", "") or ""),
            status=str(data.get("status", "pending") or "pending"),
            approved_by=str(data.get("approved_by", "") or ""),
            approved_at=str(data.get("approved_at", "") or ""),
            reject_reason=str(data.get("reject_reason", "") or ""),
        )
