"""Pure helpers for the Ozon listing workbench flow."""
from __future__ import annotations

import json
import re
from typing import Any

from .services import OzonQualityScorer, _extract_public_image_urls


WALLET_CATEGORY_ID = 17027904
WALLET_TYPE_ID = 93338
WALLET_TYPE_NAME_RU = "Кошелек"

TRUSTED_BRAND_SOURCES = {"operator", "manual", "product_data", "known_brand", "rule", "ozon_dictionary"}
UNTRUSTED_BRAND_SOURCES = {"scraped_shop", "shop", "store", "seller", "collected_shop"}


def match_wallet_category(product: dict) -> dict:
    text = " ".join(
        str(product.get(key, ""))
        for key in ("skc", "title", "name", "category", "description")
    ).lower()
    wallet_tokens = ("wallet", "wristlet", "кошелек", "кошелёк", "портмоне", "бумажник")
    if str(product.get("skc", "")).upper().startswith("WALLET-") or any(token in text for token in wallet_tokens):
        return {
            "matched": True,
            "description_category_id": WALLET_CATEGORY_ID,
            "type_id": WALLET_TYPE_ID,
            "name": WALLET_TYPE_NAME_RU,
            "path": "Галантерея и аксессуары > Аксессуары > Кошелек",
            "confidence": 0.98,
            "source": "wallet_rule",
        }
    return {
        "matched": False,
        "description_category_id": None,
        "type_id": None,
        "name": "",
        "path": "",
        "confidence": 0.0,
        "source": "no_rule_match",
    }


def build_wallet_rich_content(image_urls: list[str]) -> dict:
    urls = [url for url in image_urls if isinstance(url, str) and url.startswith(("http://", "https://"))]
    titles = [
        "Компактный кошелек на каждый день",
        "Продуманное хранение",
        "Нейлон, RFID-защита и легкий уход",
    ]
    texts = [
        "Кошелек удобно носить в сумке или на запястье благодаря съемному ремешку.",
        "Три отделения на молнии помогают разложить карты, купюры, монеты и документы.",
        "Прочный нейлон, металлическая фурнитура и RFID-защита подходят для поездок и ежедневных дел.",
    ]
    blocks: list[dict] = []
    for index, url in enumerate(urls[:3]):
        blocks.append({
            "imgLink": "",
            "img": {
                "src": url,
                "srcMobile": url,
                "alt": titles[index],
                "position": "width_full",
                "positionMobile": "width_full",
                "width": 900,
                "height": 1200,
                "widthMobile": 640,
                "heightMobile": 853,
            },
            "title": {
                "content": [titles[index]],
                "size": "size4",
                "align": "left",
                "color": "color1",
            },
            "text": {
                "size": "size2",
                "align": "left",
                "color": "color1",
                "content": [texts[index]],
            },
        })
    return {"content": [{"widgetName": "raShowcase", "type": "billboard", "blocks": blocks}], "version": 0.3}


def rich_content_to_attribute_value(image_urls: list[str]) -> str:
    return json.dumps(build_wallet_rich_content(image_urls), ensure_ascii=False)


def collect_ozon_skus(value: Any) -> list[int]:
    skus: list[int] = []

    def add(candidate: Any) -> None:
        try:
            sku = int(candidate)
        except (TypeError, ValueError):
            return
        if sku > 0 and sku not in skus:
            skus.append(sku)

    if isinstance(value, dict):
        for key in ("sku", "fbo_sku", "fbs_sku"):
            add(value.get(key))
        for source in value.get("sources", []) or []:
            if isinstance(source, dict):
                for key in ("sku", "fbo_sku", "fbs_sku"):
                    add(source.get(key))
        for item in value.get("items", []) or []:
            for sku in collect_ozon_skus(item):
                add(sku)
        result = value.get("result")
        if isinstance(result, dict):
            for item in result.get("items", []) or []:
                for sku in collect_ozon_skus(item):
                    add(sku)
    elif isinstance(value, list):
        for item in value:
            for sku in collect_ozon_skus(item):
                add(sku)
    return skus


def _find_attr(attrs: list[dict], attr_id: int) -> dict | None:
    for attr in attrs or []:
        if str(attr.get("attribute_id") or attr.get("id")) == str(attr_id):
            return attr
    return None


def _rich_content_valid(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return False
    if not isinstance(value, dict) or value.get("version") != 0.3:
        return False
    content = value.get("content")
    if not isinstance(content, list) or not content:
        return False
    first = content[0]
    return (
        isinstance(first, dict)
        and first.get("widgetName") == "raShowcase"
        and isinstance(first.get("blocks"), list)
        and bool(first.get("blocks"))
    )


def validate_workbench_payload(payload: dict) -> dict:
    issues: list[str] = []
    warnings: list[str] = []

    if not payload.get("category_id"):
        issues.append("缺少 Ozon 类目")
    if not payload.get("type_id"):
        issues.append("缺少 Ozon type_id")
    for key, label in (("name", "标题"), ("description", "描述"), ("price", "价格"), ("offer_id", "offer_id")):
        if not str(payload.get(key, "")).strip():
            issues.append(f"缺少{label}")

    images = payload.get("images") or []
    public_urls = _extract_public_image_urls(images, 10)
    if len(public_urls) < 5:
        issues.append("至少需要 5 张可公开访问的商品图片")
    elif len(public_urls) < 8:
        warnings.append("图片少于 8 张，Ozon 媒体评分仍有提升空间")

    skus = payload.get("skus") or []
    if not skus:
        issues.append("缺少 SKU/变体行")

    attrs = payload.get("attributes") or []
    brand = _find_attr(attrs, 85)
    if brand:
        source = str(brand.get("source", "")).strip().lower()
        if source in UNTRUSTED_BRAND_SOURCES or (source and source not in TRUSTED_BRAND_SOURCES):
            issues.append("品牌来源不可信，不能直接使用采集店铺名")
        if not brand.get("dictionary_value_id"):
            warnings.append("品牌建议使用 Ozon dictionary_value_id")

    rich_attr = _find_attr(attrs, 11254)
    if rich_attr:
        if not _rich_content_valid(rich_attr.get("value")):
            issues.append("Rich Content JSON 不符合 Ozon raShowcase 模板")
    else:
        warnings.append("缺少 Rich Content JSON，官方文本评分会降低")

    local_report = OzonQualityScorer.score(payload)
    can_submit = not issues and local_report["score"] >= 75
    return {
        "success": True,
        "can_submit": can_submit,
        "score": local_report["score"],
        "target_score": 75,
        "issues": issues,
        "warnings": warnings + local_report["warnings"],
        "sections": local_report["sections"],
        "public_image_count": len(public_urls),
    }


def variant_token(value: str) -> str:
    parts = re.split(r"[-_\s]+", str(value or "").lower())
    return parts[-1] if parts else ""
