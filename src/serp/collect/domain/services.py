"""
Collect 域 - 领域服务（纯业务逻辑，无 I/O）。
"""
import re

from .value_objects import CollectUrl

CATEGORY_CODES = {
    "钱包": "WALLET", "手机壳": "PHCA", "背包": "BACK",
    "支架": "STAND", "手表": "WATCH", "帽子": "HATS",
    "首饰": "JEWL", "鞋子": "SHOE", "服装": "GARM",
    "家居": "HOME", "电子": "ELEC", "玩具": "TOYS",
    "汽车配件": "AUTO", "办公用品": "OFFC", "美妆": "BEAU",
    "运动": "SPRT", "宠物": "PETS", "食品": "FOOD",
    "箱包": "LUGG", "家具": "FURN",
}

CATEGORY_KEYWORDS = {
    "钱包": ["wallet", "钱包", "卡包", "钱夹"],
    "手机壳": ["phone case", "手机壳", "手机套", "case for"],
    "背包": ["backpack", "背包", "双肩包", "书包"],
    "支架": ["stand", "支架", "holder", "支撑"],
    "手表": ["watch", "手表", "腕表", "手环"],
    "帽子": ["hat", "cap", "帽子", "棒球帽"],
    "首饰": ["jewelry", "jewellery", "首饰", "项链", "手链", "戒指", "耳环"],
    "鞋子": ["shoe", "shoes", "鞋子", "运动鞋", "靴子"],
    "服装": ["clothing", "apparel", "服装", "衣服", "t-shirt", "shirt", "dress"],
    "家居": ["home", "家居", "家装", "装饰"],
    "电子": ["electronic", "电子", "充电", "cable", "adapter"],
    "玩具": ["toy", "toys", "玩具", "玩偶"],
    "汽车配件": ["auto", "car", "汽车", "车载"],
    "办公用品": ["office", "办公", "文具"],
    "美妆": ["beauty", "cosmetic", "美妆", "化妆", "护肤"],
    "运动": ["sport", "sports", "运动", "健身"],
    "宠物": ["pet", "宠物", "猫", "狗"],
    "食品": ["food", "snack", "食品", "零食", "饮料"],
    "箱包": ["luggage", "suitcase", "行李箱", "旅行箱"],
    "家具": ["furniture", "家具", "桌子", "椅子", "沙发"],
}


class CategorizationService:
    """产品品类分类领域服务"""

    @staticmethod
    def guess_category(title: str) -> str:
        """根据产品标题猜测品类"""
        title_lower = title.lower()
        for category, kws in CATEGORY_KEYWORDS.items():
            for kw in kws:
                if kw in title_lower:
                    return category
        return "其他"

    @staticmethod
    def generate_sku(skc_base: str, variant_name: str, index: int) -> str:
        """为变体生成 SKU"""
        variant = variant_name.strip().upper() if variant_name else ""
        variant_slug = re.sub(r'[^A-Z0-9]', '', variant) or f"V{index:02d}"
        return f"{skc_base}-{variant_slug}"


class UrlService:
    """URL 相关领域服务"""

    @staticmethod
    def extract_platform(url: str) -> str:
        if not url:
            return "unknown"
        return CollectUrl.extract_platform(CollectUrl(url))

    @staticmethod
    def extract_target_url(req_body: dict) -> str | None:
        """从请求体中提取目标采集 URL（DXM 场景）"""
        if not isinstance(req_body, dict):
            return None
        for key in ("url", "sourceUrl", "productUrl", "link", "targetUrl", "originUrl"):
            val = req_body.get(key, "")
            if isinstance(val, str) and val.startswith("http"):
                return val
        data = req_body.get("data")
        if isinstance(data, dict):
            for key in ("url", "sourceUrl", "productUrl"):
                val = data.get(key, "")
                if isinstance(val, str) and val.startswith("http"):
                    return val
        return None
