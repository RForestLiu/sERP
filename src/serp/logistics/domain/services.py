"""
Logistics 域 - 领域服务（纯业务逻辑，无 I/O）。
"""
from .value_objects import ChannelConfig, ParcelSpec, MatchedChannel


# 排序优先级：Economy > Standard，PUDO > Courier，价格从低到高
_MODE_ORDER = {"Standard": 0, "Economy": 1}
_DELIVERY_ORDER = {"PUDO": 0, "Courier": 1}


class ChannelMatchingService:
    """物流渠道匹配服务"""

    @staticmethod
    def match(parcel: ParcelSpec, channels: list[ChannelConfig]) -> list[MatchedChannel]:
        results = []
        for ch in channels:
            if not ChannelMatchingService._matches_parcel(parcel, ch):
                continue
            billing_weight, formula = ChannelMatchingService._calc_billing(parcel, ch)
            cost = ch.base_fee + ch.per_gram_fee * billing_weight
            results.append(MatchedChannel(
                channel_id=ch.id,
                channel_name=ch.name,
                category_cn=ch.category_cn,
                mode=ch.mode,
                mode_cn=ch.mode_cn,
                delivery=ch.delivery,
                delivery_cn=ch.delivery_cn,
                cost=cost,
                formula=f"¥{ch.base_fee:.2f} + ¥{ch.per_gram_fee:.4f}/g × {formula}",
                transit_days=ch.transit_days,
                billing_type=ch.billing_type,
            ))
        return ChannelMatchingService._sort(results)

    @staticmethod
    def _matches_parcel(parcel: ParcelSpec, ch: ChannelConfig) -> bool:
        if parcel.weight_g < ch.min_weight_g or parcel.weight_g > ch.max_weight_g:
            return False
        if parcel.value_rub > 0:
            if ch.min_value_rub > 0 and parcel.value_rub < ch.min_value_rub:
                return False
            if ch.max_value_rub < float("inf") and parcel.value_rub > ch.max_value_rub:
                return False
        if parcel.length_cm > 0 and parcel.width_cm > 0 and parcel.height_cm > 0:
            max_side = max(parcel.length_cm, parcel.width_cm, parcel.height_cm)
            sum_sides = parcel.length_cm + parcel.width_cm + parcel.height_cm
            if max_side > ch.max_side_cm:
                return False
            if sum_sides > ch.max_sum_sides_cm:
                return False
        return True

    @staticmethod
    def _calc_billing(parcel: ParcelSpec, ch: ChannelConfig) -> tuple[float, str]:
        if ch.billing_type == "volumetric" and parcel.length_cm > 0:
            vol_weight = parcel.length_cm * parcel.width_cm * parcel.height_cm / 12000
            billing_weight = max(parcel.weight_g, vol_weight)
            formula = f"max({parcel.weight_g:.0f}g, {parcel.length_cm:.0f}×{parcel.width_cm:.0f}×{parcel.height_cm:.0f}/12000={vol_weight:.0f}g) = {billing_weight:.0f}g"
            return billing_weight, formula
        return parcel.weight_g, f"{parcel.weight_g:.0f}g"

    @staticmethod
    def _sort(results: list[MatchedChannel]) -> list[MatchedChannel]:
        return sorted(results, key=lambda m: (
            _MODE_ORDER.get(m.mode, 99),
            _DELIVERY_ORDER.get(m.delivery, 99),
            m.cost,
        ))
