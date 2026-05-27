"""
Listing 域 - 领域服务（纯业务逻辑，无 I/O 依赖）。
"""
from __future__ import annotations

import re
from typing import Any


# ── Ozon 上架评分 ──

OZON_LISTING_SCORE_TARGET = 80


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转 float"""
    try:
        if value is None:
            return default
        text = str(value).strip().replace(",", ".")
        if not text:
            return default
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else default
    except Exception:
        return default


def _is_public_product_image_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    low = url.strip().lower()
    if not low.startswith(("http://", "https://")):
        return False
    if low.endswith(".svg") or "sprite" in low or "aicid=community" in low:
        return False
    if any(token in low for token in ("_ss64_", "_us40_", "_uc154", "_sr89", "_sr166", "_ul165", "_ul330", "_ul495")):
        return False
    if not any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp")):
        return False
    return True


def _extract_public_image_urls(images: list, limit: int = 10) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for img in images or []:
        url = img.get("url", "") if isinstance(img, dict) else str(img)
        if not _is_public_product_image_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


class OzonQualityScorer:
    """Ozon 上架 payload 质量评分服务（纯逻辑，无 I/O）"""

    @staticmethod
    def score(data: dict) -> dict:
        """对 Ozon 上架 payload 打分，返回评分报告"""
        issues: list[str] = []
        warnings: list[str] = []
        sections: list[dict] = []

        def _add_section(name: str, points: float, max_points: int, detail: str):
            sections.append({"name": name, "points": points, "max_points": max_points, "detail": detail})

        name = str(data.get("name", "")).strip()
        description = str(data.get("description", "")).strip()
        price = _to_float(data.get("price"))
        offer_id = str(data.get("offer_id", "")).strip()
        category_id = data.get("category_id")
        type_id = data.get("type_id")
        attrs = data.get("attributes") or []
        skus = data.get("skus") or []
        rich_content = data.get("rich_content") or []

        # ── 类目 (15 pts) ──
        category_points = 10.0 if category_id else 0.0
        if not category_id:
            issues.append("缺少 Ozon 类目 description_category_id")
        if type_id:
            category_points += 5
        else:
            warnings.append("缺少 type_id，部分 Ozon 类目可能导入失败")
        _add_section("类目", category_points, 15, "类目 ID 与 type_id")

        # ── 基础信息 (15 pts) ──
        basic_points = 0.0
        if 20 <= len(name) <= 200:
            basic_points += 6
        elif name:
            basic_points += 3
            warnings.append("商品标题长度不理想，建议 20-200 字符")
        else:
            issues.append("缺少商品标题")
        if len(description) >= 300:
            basic_points += 5
        elif description:
            basic_points += 2
            warnings.append("商品描述偏短，建议补充用途、材质、容量、RFID 等卖点")
        else:
            issues.append("缺少商品描述")
        if offer_id:
            basic_points += 2
        else:
            issues.append("缺少主 offer_id")
        if price > 0:
            basic_points += 2
        else:
            issues.append("缺少有效售价")
        _add_section("基础信息", basic_points, 15, "标题、描述、offer_id、售价")

        # ── 属性完整度 (25 pts) ──
        filled_attrs = [a for a in attrs if a.get("attribute_id") and str(a.get("value", "")).strip()]
        attr_points = min(18.0, len(filled_attrs) * 1.2)
        attr_text = " ".join(str(a) for a in attrs).lower()
        if any(token in attr_text for token in ("материал", "material", "экокожа", "5309")):
            attr_points += 2
        else:
            warnings.append("未识别到材料属性，wallet 类目建议必填")
        if any(token in attr_text for token in ("цвет", "color", "10096", "10097")):
            attr_points += 2
        else:
            warnings.append("未识别到颜色属性，变体商品建议补齐")
        if any(token in attr_text for token in ("бренд", "brand", '"85"')):
            attr_points += 1.5
        if rich_content:
            attr_points += 1.5
        else:
            warnings.append("缺少 Rich Content/JSON 富文本，会影响卡片质量")
        attr_points = min(25.0, attr_points)
        if attr_points < 15:
            issues.append("Ozon 属性填写不足，建议先拉取类目必填属性并补齐")
        _add_section("属性完整度", round(attr_points, 1), 25, f"已填属性 {len(filled_attrs)} 个")

        # ── 媒体素材 (20 pts) ──
        raw_images = data.get("images") or []
        base_image_urls = _extract_public_image_urls(raw_images, 10)
        media_points = min(15.0, len(base_image_urls) * 3.0)
        if len(base_image_urls) >= 5:
            media_points += 3
        if rich_content:
            media_points += 2
        if not base_image_urls:
            issues.append("没有可提交到 Ozon 的公网商品图片 URL")
        elif raw_images and len(base_image_urls) < len(raw_images):
            rejected = len(raw_images) - len(base_image_urls)
            warnings.append(f"已过滤 {rejected} 张非商品图/缩略图/图标")
        _add_section("媒体素材", min(20.0, media_points), 20, f"可用主图 {len(base_image_urls)} 张")

        # ── 变体与库存 (15 pts) ──
        sku_points = 0.0
        valid_skus: list[dict] = []
        sku_offer_ids: set[str] = set()
        for sku in skus:
            sku_id = str(sku.get("sku_code") or sku.get("name") or "").strip()
            sku_price = _to_float(sku.get("price") or data.get("price"))
            if sku_id and sku_price > 0:
                valid_skus.append(sku)
            if sku_id:
                sku_offer_ids.add(sku_id)
        if skus and len(valid_skus) == len(skus):
            sku_points += 8
        elif valid_skus:
            sku_points += 4
            warnings.append("部分 SKU 缺少 offer_id 或价格")
        else:
            issues.append("缺少可提交的 SKU/变体")
        if len(sku_offer_ids) == len(skus) and skus:
            sku_points += 3
        else:
            warnings.append("SKU offer_id 为空或重复")
        if skus and all(_to_float(s.get("stock"), -1) >= 0 for s in skus):
            sku_points += 2
        else:
            warnings.append("部分 SKU 缺少库存")
        if len(skus) >= 2:
            sku_points += 2
        _add_section("变体与库存", min(15.0, sku_points), 15, f"SKU {len(skus)} 个")

        # ── 价格物流 (10 pts) ──
        ops_points = 0.0
        if price > 0:
            ops_points += 3
        if any(_to_float(s.get("old_price")) > _to_float(s.get("price")) > 0 for s in skus):
            ops_points += 2
        else:
            warnings.append("未识别到有效原价，建议原价高于售价")
        if re.search(r"(4383|weight|вес)", attr_text):
            ops_points += 2
        else:
            warnings.append("缺少重量属性，wallet 当前应优先使用实测重量")
        if re.search(r"(height|width|depth|length|尺寸|размер|5355|5299|6573)", attr_text):
            ops_points += 2
        else:
            warnings.append("缺少尺寸属性，Ozon 物流和审核可能受影响")
        if data.get("barcode") or any(str(s.get("barcode", "")).strip() for s in skus):
            ops_points += 1
        else:
            warnings.append("未填写条码；如 Ozon 允许自动生成，可后续补")
        _add_section("价格物流", min(10.0, ops_points), 10, "价格、原价、重量、尺寸、条码")

        score = round(sum(float(s["points"]) for s in sections))
        return {
            "score": score,
            "target_score": OZON_LISTING_SCORE_TARGET,
            "can_submit": score >= OZON_LISTING_SCORE_TARGET and not issues,
            "sections": sections,
            "issues": issues,
            "warnings": warnings,
            "filtered_image_count": len(_extract_public_image_urls(data.get("images") or [], 10)),
            "rejected_image_count": max(0, len(data.get("images") or []) - len(_extract_public_image_urls(data.get("images") or [], 10))),
        }


# ── 跨品类通用属性预设提示词库 ──

COMMON_ATTRIBUTE_PRESETS = {
    "title_name": {
        "keywords": ["название", "наименование", "имя", "name", "title", "название товара",
                     "名称", "标题", "наименование товара", "полное название"],
        "instruction": """【标题填充 — 俄语优化规则】
从产品数据提取核心信息生成俄语标题：
1. 去除品牌名、删除商标符号（™®×•·）
2. 结构：商品类型 + 关键特征1 + 关键特征2 + 适用对象
3. 控制在 50~100 字符
4. 仅填俄语文本""",
    },
    "description": {
        "keywords": ["описание", "description", "аннотация", "描述", "说明",
                     "商品描述", "подробное описание", "описание товара"],
        "instruction": """【描述填充 — 4+1 结构化框架】
用俄语生成客观、信息型的结构化描述：
① 功能用途（1-2句）— 产品是什么、做什么
② 材质设计（1-2句）— 材料、工艺、结构
③ 适用场景（1句）— 什么人、什么场合使用
④ 优势特点（1-2句）— 差异化卖点
要求：禁止品牌名和特殊符号（— × • ™ ®）、每段≤4句、自然流畅""",
    },
    "hashtags": {
        "keywords": ["hashtag", "хэштег", "тег", "тэг", "标签", "метка",
                     "theme_tags", "поисковые теги", "ключевые слова"],
        "instruction": """【Ozon标签 — 5步法生成】
生成俄语标签（10~22个），每个≤28字符，#开头，空格分隔。
① 提取核心词：材质、功能、规格
② 对齐Ozon高频搜索词
③ 分组排序：功能类 > 用户群体类 > 场景类 > 节日类(可选)
④ 去重校验：不含品牌、不含特殊符号、独立有搜索意义
⑤ 数量：10~22个标签，一行空格分隔
节日标签：仅距离节日≤2个月且产品适合送礼时加1-3个""",
    },
    "gender_audience": {
        "keywords": ["пол", "аудитория", "для кого", "性别", "受众", "适用人群", "целевая аудитория"],
        "instruction": """【受众/性别属性】
从产品标题/描述判断目标受众性别：
- 明确提及 "women/женский" → "Женский"
- 明确提及 "men/мужской" → "Мужской"
- 通用中性 → "Унисекс"
仅从可选值中选取，无把握则留空""",
    },
    "material": {
        "keywords": ["материал", "material", "材质", "材料", "состав", "成分"],
        "instruction": """【材质属性】
从产品标题/描述提取材质信息，翻译为俄语：
- leather/faux leather → "Натуральная кожа" / "Искусственная кожа"
- cotton → "Хлопок"
- polyester → "Полиэстер"
dictionary 类型从可选值中精确选取""",
    },
    "color": {
        "keywords": ["цвет", "color", "цвета", "颜色", "色彩", "расцветка"],
        "instruction": """【颜色属性】
从产品标题/描述提取颜色信息，翻译为俄语：
dictionary 类型从可选值中精确选取""",
    },
    "series_model": {
        "keywords": ["коллекция", "серия", "系列", "型号", "модель", "артикул"],
        "instruction": """【系列/型号属性】
从产品数据提取系列名/型号（如有），若无则留空。
仅填产品明确的系列名，不编造""",
    },
    "warranty": {
        "keywords": ["гарантия", "保修", "срок гарантии", "гарантийный срок", "warranty"],
        "instruction": """【保修属性】
默认填 "12 месяцев"（12个月保修，俄罗斯标准）。
如有特殊保修条款则如实填写""",
    },
    "packaging": {
        "keywords": ["упаковка", "包装", "комплектация", "в комплекте", "package"],
        "instruction": """【包装/配件属性】
从产品描述中提取包装内容或配件清单，翻译为俄语。
如产品描述提到 "包装含/comes with/includes"，据此填写。
不确定则留空""",
    },
    "quantity": {
        "keywords": ["количество", "数量", "комплект", "в наборе", "件数", "个数"],
        "instruction": """【数量/件数属性】
从产品描述提取数量信息（如 2-pack/3件套），填写俄语数字。
default: "1 шт." if no multi-pack info""",
    },
    "closure": {
        "keywords": ["застежка", "扣件", "闭合", "拉链", "молния", "липучка", "кнопка"],
        "instruction": """【闭合方式属性】
从产品描述判断闭合方式：
- zipper → "Молния"
- magnetic → "Магнитная"
- snap → "Кнопка"
dictionary 类型从可选值中精确选取""",
    },
    "age": {
        "keywords": ["возраст", "18+", "年龄", "age", "ограничение"],
        "instruction": """【年龄限制属性】
default: 若产品无明确年龄限制，填 0(=无限制) 或留空。
dictionary 类型从可选值中精确选取""",
    },
    "country": {
        "keywords": ["страна", "原产", "страна производства", "сделано в", "country"],
        "instruction": """【原产国属性】
default: "Китай"（中国大陆制造）。
如产品数据明确标注其他产地(如越南/印度)，则如实填写。
dictionary 类型从可选值中精确选取""",
    },
}

NON_REQUIRED_COMMON_ATTR_MAP = {
    "hashtag": "hashtags",
    "хэштег": "hashtags",
    "тег": "hashtags",
    "标签": "hashtags",
    "коллекция": "series_model",
    "серия": "series_model",
    "系列": "series_model",
    "гарантия": "warranty",
    "保修": "warranty",
    "упаковка": "packaging",
    "包装": "packaging",
    "количество": "quantity",
    "комплект": "quantity",
    "数量": "quantity",
    "застежка": "closure",
    "扣件": "closure",
    "闭合": "closure",
    "молния": "closure",
    "возраст": "age",
    "18+": "age",
    "年龄": "age",
    "страна": "country",
    "原产": "country",
    "пол": "gender_audience",
    "性别": "gender_audience",
    "для кого": "gender_audience",
    "материал": "material",
    "材质": "material",
    "цвет": "color",
    "颜色": "color",
}


class AttributePresetMatcher:
    """为 Ozon 属性匹配预设填充规则（纯逻辑）"""

    @staticmethod
    def match(ozon_attributes: list[dict]) -> tuple[dict, dict]:
        """返回: (preset_map, non_required_presets)
          - preset_map: {attr_id: instruction}
          - non_required_presets: {attr_id: instruction}（仅非必填且匹配到的）
        """
        preset_map: dict[int, str] = {}
        non_required_presets: dict[int, str] = {}

        for attr in ozon_attributes:
            attr_id = attr.get("id")
            if attr_id is None:
                continue
            attr_name = attr.get("name", "") or ""
            attr_name_cn = attr.get("name_cn", "") or ""
            is_required = attr.get("is_required", False)

            search_text = f"{attr_name_cn} {attr_name}".lower()
            instruction: str | None = None

            for _key, preset in COMMON_ATTRIBUTE_PRESETS.items():
                for kw in preset["keywords"]:
                    if kw.lower() in search_text:
                        instruction = preset["instruction"]
                        break
                if instruction:
                    break

            if not instruction and not is_required:
                for kw, preset_key in NON_REQUIRED_COMMON_ATTR_MAP.items():
                    if kw.lower() in search_text:
                        instruction = COMMON_ATTRIBUTE_PRESETS.get(preset_key, {}).get("instruction", "")
                        break

            if instruction:
                preset_map[attr_id] = instruction
                if not is_required:
                    non_required_presets[attr_id] = instruction

        return preset_map, non_required_presets


class DeterministicPreFiller:
    """从已有数据中提取可直接填入的确定值（不依赖 AI）"""

    @staticmethod
    def extract(manual_data: dict, product_data: dict) -> dict[str, str]:
        hints: dict[str, str] = {}

        if manual_data:
            weight = manual_data.get("effective_weight_g") or manual_data.get("weight_g", "")
            if weight:
                hints["weight_g"] = str(weight)
                hints["weight_source"] = str(manual_data.get("effective_weight_source", "measured"))
            size_spec = manual_data.get("effective_size_spec") or manual_data.get("size_spec", "")
            if size_spec:
                hints["size_spec"] = str(size_spec)
                hints["size_source"] = str(manual_data.get("effective_size_source", "measured"))
            spec = manual_data.get("spec", "")
            if spec:
                hints["spec"] = str(spec)
            cost_price = manual_data.get("cost_price", "")
            if cost_price:
                hints["cost_price_cny"] = str(cost_price)

        if product_data:
            attrs = product_data.get("attributes", {}) or {}
            if isinstance(attrs, dict):
                for key, val in attrs.items():
                    if val and isinstance(val, str):
                        kl = key.lower()
                        if any(kw in kl for kw in ["color", "colour"]):
                            hints["known_color"] = val
                        elif any(kw in kl for kw in ["material"]):
                            hints["known_material"] = val
                        elif any(kw in kl for kw in ["brand"]) and "нет бренда" not in val.lower():
                            hints["known_brand"] = val
            details = product_data.get("product_details") or {}
            if "size_spec" not in hints and isinstance(details, dict):
                parsed = DeterministicPreFiller._extract_dimension_hint(details)
                if parsed:
                    hints["size_spec"] = parsed[0]
                    hints["size_source"] = parsed[1]

        return hints

    @staticmethod
    def _extract_dimension_hint(details: dict) -> tuple[str, str] | None:
        for key, val in details.items():
            key_text = str(key).lower()
            if not val or not any(part in key_text for part in ["dimension", "size"]):
                continue
            text = str(val)
            label_match = re.search(
                r'([\d.]+)\s*"?\s*d\s*x\s*([\d.]+)\s*"?\s*w\s*x\s*([\d.]+)\s*"?\s*h',
                text,
                re.IGNORECASE,
            )
            numbers = label_match.groups() if label_match else re.findall(r"[\d.]+", text)[:3]
            if len(numbers) < 3:
                continue
            multiplier = 2.54 if re.search(r'inch|inches|"', text, re.IGNORECASE) else 1
            dims = [round(float(num) * multiplier, 1) for num in numbers[:3]]
            size_spec = "x".join(str(dim).rstrip("0").rstrip(".") for dim in dims) + "cm"
            return size_spec, f"product_details.{key}"
        return None
