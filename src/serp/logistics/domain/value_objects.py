"""
Logistics 域 - 值对象。
"""
from dataclasses import dataclass, field

from src.serp.shared import ValueObject


@dataclass(frozen=True)
class ChannelConfig(ValueObject):
    """物流渠道配置 — 不可变值对象"""
    id: str
    name: str
    category_cn: str = ""
    mode: str = ""           # "Standard" | "Economy"
    mode_cn: str = ""
    delivery: str = ""       # "PUDO" | "Courier"
    delivery_cn: str = ""
    base_fee: float = 0.0
    per_gram_fee: float = 0.0
    min_weight_g: float = 0.0
    max_weight_g: float = float("inf")
    min_value_rub: float = 0.0
    max_value_rub: float = float("inf")
    max_side_cm: float = float("inf")
    max_sum_sides_cm: float = float("inf")
    billing_type: str = "actual_weight"  # "actual_weight" | "volumetric"
    transit_days: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelConfig":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            category_cn=data.get("category_cn", ""),
            mode=data.get("mode", ""),
            mode_cn=data.get("mode_cn", ""),
            delivery=data.get("delivery", ""),
            delivery_cn=data.get("delivery_cn", ""),
            base_fee=float(data.get("base_fee", 0)),
            per_gram_fee=float(data.get("per_gram_fee", 0)),
            min_weight_g=float(data.get("min_weight_g", 0)),
            max_weight_g=float(data.get("max_weight_g", float("inf"))),
            min_value_rub=float(data.get("min_value_rub", 0)),
            max_value_rub=float(data.get("max_value_rub", float("inf"))),
            max_side_cm=float(data.get("max_side_cm", float("inf"))),
            max_sum_sides_cm=float(data.get("max_sum_sides_cm", float("inf"))),
            billing_type=data.get("billing_type", "actual_weight"),
            transit_days=str(data.get("transit_days", "")),
        )


@dataclass(frozen=True)
class ParcelSpec(ValueObject):
    """包裹规格 — 计算输入"""
    weight_g: float
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
    value_rub: float = 0.0


@dataclass(frozen=True)
class MatchedChannel(ValueObject):
    """匹配结果 — 计算输出"""
    channel_id: str
    channel_name: str
    category_cn: str
    mode: str
    mode_cn: str
    delivery: str
    delivery_cn: str
    cost: float
    formula: str
    transit_days: str
    billing_type: str

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "category_cn": self.category_cn,
            "mode": self.mode,
            "mode_cn": self.mode_cn,
            "delivery": self.delivery,
            "delivery_cn": self.delivery_cn,
            "cost": round(self.cost, 2),
            "formula": self.formula,
            "transit_days": self.transit_days,
            "billing_type": self.billing_type,
        }
