"""
Product 域 - 应用服务（用例编排）。
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional, Callable, TYPE_CHECKING
from urllib.parse import quote

import requests

from src.serp.shared import Result, EventBus

from ..domain.entities import Product, ProductCollection, CRITICAL_FIELDS
from ..domain.value_objects import ManualData, StoreStatusEntry
from ..domain.events import (
    ProductDeleted,
    ProductManualUpdated,
    SpecsCollected,
    ProductAutoExtracted,
    StoreStatusChanged,
    ImageSetsUpdated,
    ProductImageUploaded,
    ProductVideoUploaded,
    ProductCriticalChangeProposed,
    ProductCriticalFieldApproved,
    ProductCriticalFieldRejected,
)
from ..domain.repositories import ProductRepository
from ..facade import ProductFacade

if TYPE_CHECKING:
    from src.serp.settings.facade import SettingsFacade

logger = logging.getLogger(__name__)

STORE_STATUSES = ["未上架", "待发布", "审核中", "已上架", "审核拒绝", "下架回归中"]

_IMG_PROXY_ALLOWED = frozenset({
    "m.media-amazon.com", "images-na.ssl-images-amazon.com",
    "images-eu.ssl-images-amazon.com", "images-fe.ssl-images-amazon.com",
    "img.alicdn.com", "cbu01.alicdn.com",
    "images.wbstatic.net", "basket.wildberries.ru",
    "cdn1.ozonusercontent.com", "cdn2.ozonusercontent.com",
})

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}


class ProductApplicationService(ProductFacade):
    """Product 域应用服务 — 实现 ProductFacade，编排领域对象和仓储。"""

    def __init__(
        self,
        product_repo: ProductRepository,
        settings_facade: "SettingsFacade",
        event_bus: EventBus,
        data_root: str,
        videos_dir: str = "",
    ):
        self._product_repo = product_repo
        self._settings = settings_facade
        self._event_bus = event_bus
        self._data_root = data_root
        self._videos_dir = videos_dir or os.path.join(data_root, "videos")

    # ==================== LLM helper ====================

    def _get_llm_config(self, feature_key: str, env_model_key: str, default_model: str) -> dict:
        """从 Settings Facade 解析 LLM 模型配置"""
        config = {
            "base_url": os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "model": os.getenv(env_model_key, default_model),
        }
        try:
            model_id = self._settings.get_feature_model(feature_key)
            if model_id:
                models = {m["id"]: m for m in self._settings.get_models() if isinstance(m, dict)}
                selected = models.get(model_id)
                if selected:
                    config["base_url"] = selected.get("base_url") or config["base_url"]
                    config["model"] = selected.get("model") or config["model"]
                    api_key_env = selected.get("api_key_env") or "DEEPSEEK_API_KEY"
                    config["api_key"] = os.getenv(api_key_env, config["api_key"])
        except Exception as exc:
            logger.warning("[product] settings model resolve failed: %s", exc)
        return config

    def _call_llm(self, config: dict, system_prompt: str, user_prompt: str,
                  validator: Callable, label: str, max_retries: int = 2) -> dict:
        """调用 LLM 并校验 JSON 返回"""
        if not config.get("api_key"):
            raise ValueError("DEEPSEEK_API_KEY not configured")

        validation_error = ""
        last_text = ""
        for attempt in range(max_retries + 1):
            prompt = user_prompt
            if validation_error:
                prompt += "\n\n上一次返回未通过程序校验：%s\n请只修正 JSON，不要解释。" % validation_error
            payload = {
                "model": config["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 800,
                "response_format": {"type": "json_object"},
            }
            if "v4-pro" in str(config["model"]).lower():
                payload["enable_thinking"] = False
            resp = requests.post(
                config["base_url"],
                headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"LLM 请求失败: HTTP {resp.status_code}: {resp.text[:300]}")
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            last_text = content
            try:
                parsed = json.loads(content.strip())
            except json.JSONDecodeError as exc:
                validation_error = f"不是合法 JSON: {exc}"
                logger.warning("[product/%s] JSON parse failed: %s", label, content[:300])
                continue
            ok, normalized, validation_error = validator(parsed)
            if ok:
                normalized["_model"] = config["model"]
                normalized["_attempts"] = attempt + 1
                return normalized
            logger.warning("[product/%s] validation failed: %s", label, validation_error)
        raise ValueError(f"{label} 结构化返回校验失败: {validation_error}; raw={last_text[:300]}")

    # ── LLM validation helpers (static, match old app.py logic) ──

    @staticmethod
    def _normalize_number(value):
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", ".")
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None

    @staticmethod
    def _has_unconverted_unit(value):
        if not isinstance(value, str):
            return False
        return bool(re.search(
            r"\b(oz|ounce|ounces|lb|lbs|pound|pounds|kg|kgs|kilogram|kilograms|mm|millimeter|millimeters|inch|inches|in|ft|feet)\b|英寸|盎司|磅|千克|公斤|毫米",
            value, re.I,
        ))

    @classmethod
    def _validate_specs_extract(cls, data):
        if not isinstance(data, dict):
            return False, {}, "顶层必须是 JSON object"
        if cls._has_unconverted_unit(data.get("weight_g")):
            return False, {}, "weight_g 必须先换算为纯克数，不能包含 oz/lb 等原始单位"
        weight = cls._normalize_number(data.get("weight_g"))
        if weight is not None and not (1 <= weight <= 50000):
            return False, {}, "weight_g 必须是 1-50000 范围内的克数"

        size_cm = data.get("size_cm") or []
        if size_cm in ("", None):
            size_cm = []
        if not isinstance(size_cm, list):
            return False, {}, "size_cm 必须是数字数组"
        normalized_size = []
        for item in size_cm:
            if cls._has_unconverted_unit(item):
                return False, {}, "size_cm 必须先换算为纯厘米数，不能包含 inch/in 等原始单位"
            number = cls._normalize_number(item)
            if number is None:
                return False, {}, "size_cm 只能包含数字"
            if not (0.1 <= number <= 500):
                return False, {}, "size_cm 每个值必须是 0.1-500 范围内的厘米数"
            normalized_size.append(round(number, 1))
        if normalized_size and len(normalized_size) not in (2, 3):
            return False, {}, "size_cm 必须是 2 或 3 个维度"
        if weight is None and not normalized_size:
            return False, {}, "weight_g 和 size_cm 至少要提取一个"

        size_spec = data.get("size_spec", "")
        if normalized_size:
            size_spec = "x".join(str(v).rstrip("0").rstrip(".") for v in normalized_size) + "cm"
        elif size_spec:
            return False, {}, "size_spec 必须由 size_cm 数字数组生成，不能直接接收模型文本"

        confidence = cls._normalize_number(data.get("confidence"))
        if confidence is None:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        evidence = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
        return True, {
            "weight_g": int(round(weight)) if weight is not None else "",
            "size_cm": normalized_size,
            "size_spec": size_spec,
            "evidence": {"weight": str(evidence.get("weight", ""))[:300], "size": str(evidence.get("size", ""))[:300]},
            "confidence": confidence,
        }, ""

    @classmethod
    def _validate_specs_review(cls, data):
        if not isinstance(data, dict):
            return False, {}, "顶层必须是 JSON object"
        if not isinstance(data.get("approved"), bool):
            return False, {}, "approved 必须是 boolean"
        candidate = {
            "weight_g": data.get("weight_g"),
            "size_cm": data.get("size_cm"),
            "size_spec": data.get("size_spec", ""),
            "evidence": data.get("evidence", {}),
            "confidence": data.get("confidence", 0),
        }
        ok, normalized, err = cls._validate_specs_extract(candidate)
        if not ok:
            return False, {}, err
        normalized["approved"] = data["approved"]
        normalized["reason"] = str(data.get("reason", ""))[:500]
        return True, normalized, ""

    @staticmethod
    def _compact_specs_source(product: Product) -> str:
        pd = product.product_data
        details = pd.get("product_details", {}) if isinstance(pd.get("product_details"), dict) else {}
        attrs = pd.get("attributes", {}) if isinstance(pd.get("attributes"), dict) else {}
        source = {
            "skc": product.skc,
            "title": product.title or pd.get("title", ""),
            "platform": product.platform,
            "category": product.category or pd.get("category", ""),
            "brand": pd.get("brand", ""),
            "attributes": attrs,
            "product_details": {k: v for k, v in details.items() if k != "_raw"},
            "about_item": pd.get("about_item", ""),
            "product_description": pd.get("product_description", ""),
            "description": pd.get("description", ""),
            "variants": pd.get("variants", {}),
        }
        return json.dumps(source, ensure_ascii=False, indent=2)[:16000]

    # ==================== CRUD queries ====================

    def list_products(self, query: str = "", platform: str = "") -> list[dict]:
        collection = self._product_repo.load_all()
        stores = self._settings.get_stores()

        results = []
        for product in collection.products:
            # Backfill store_status
            view = product.to_view(store_ids=[s["id"] for s in stores])

            # Manual data migration (old schema compat)
            md = view.get("manual_data", {})
            if isinstance(md, dict):
                # Merge old length_cm/width_cm/height_cm into size_spec
                if md.get("length_cm") or md.get("width_cm") or md.get("height_cm"):
                    if not md.get("size_spec"):
                        parts = [md.get("length_cm", ""), md.get("width_cm", ""), md.get("height_cm", "")]
                        if any(parts):
                            md["size_spec"] = "x".join(p for p in parts if p) + "cm"
                if md.get("color") or md.get("material"):
                    if not md.get("spec"):
                        parts = [md.get("color", ""), md.get("material", "")]
                        md["spec"] = "/".join(p for p in parts if p)
                for old_key in ["length_cm", "width_cm", "height_cm", "color", "material"]:
                    md.pop(old_key, None)

            # Thumbnail backfill
            if not view.get("thumbnail"):
                images_dir = product.images_dir
                if images_dir and os.path.exists(images_dir):
                    for root, _dirs, files in os.walk(images_dir):
                        for fname in sorted(files):
                            if os.path.splitext(fname)[1].lower() in IMAGE_EXTENSIONS:
                                rel = os.path.relpath(os.path.join(root, fname), images_dir).replace("\\", "/")
                                view["thumbnail"] = f"/product_images/{product.skc}/{rel}"
                                break
                        if view.get("thumbnail"):
                            break
                if not view.get("thumbnail"):
                    view["thumbnail"] = ""

            results.append(view)

        # Filtering
        if query:
            q = query.lower()
            results = [r for r in results if q in (r.get("title", "") or "").lower()
                       or q in (r.get("skc", "") or "").lower()
                       or q in json.dumps(r.get("product_data", {}), ensure_ascii=False).lower()]
        if platform:
            results = [r for r in results if r.get("platform", "") == platform]

        return results

    def get_product(self, skc: str) -> dict:
        product = self._find_product_or_raise(skc)
        stores = self._settings.get_stores()
        return product.to_view(store_ids=[s["id"] for s in stores])

    def update_manual(self, skc: str, data: dict) -> dict:
        product = self._find_product_or_raise(skc)
        product.update_manual(
            weight_g=data.get("weight_g", ""),
            size_spec=data.get("size_spec", ""),
            spec=data.get("spec", ""),
            cost_price=data.get("cost_price", ""),
        )
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())
        return {"success": True, "skc": skc}

    def delete_product(self, skc: str):
        product = self._find_product_or_raise(skc)
        self._product_repo.delete(skc)
        self._event_bus.publish(ProductDeleted(skc=skc, title=product.title))

    # ── Store status ──

    def update_store_status(self, skc: str, data: dict) -> dict:
        store_id = data.get("store_id", "")
        new_status = data.get("status", "")
        if not store_id or new_status not in STORE_STATUSES:
            raise ValueError("参数无效: store_id 或 status 不合法")
        product = self._find_product_or_raise(skc)
        product.update_store_status(store_id, new_status)
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())
        return {"success": True, "skc": skc, "store_id": store_id, "status": new_status}

    # ==================== Specs extraction ====================

    def extract_specs(self, skc: str) -> dict:
        product = self._find_product_or_raise(skc)
        source_text = self._compact_specs_source(product)

        extract_config = self._get_llm_config("product_specs_extract", "DEEPSEEK_AUTO_FILL_MODEL", "deepseek-v4-flash")
        review_config = self._get_llm_config("product_specs_review", "DEEPSEEK_REVIEW_MODEL", "deepseek-v4-flash")

        system_extract = (
            "你是电商商品数据抽取助手。必须只返回 JSON object。\n"
            "任务：从采集到的商品资料里抽取商品本体的重量和尺寸，并统一换算成国际单位：重量 g，尺寸 cm。\n"
            "规则：\n"
            "1. item/package/display 等字段冲突时，优先选择商品本体尺寸；包装尺寸只有在没有商品本体尺寸时才使用。\n"
            "2. 盎司/磅必须换算成 g：1 oz = 28.3495 g, 1 lb = 453.592 g。\n"
            "3. inch/in/英寸必须换算成 cm：1 inch = 2.54 cm。\n"
            "4. 不确定的字段留空，不要猜。\n"
            '返回结构必须是：\n'
            '{"weight_g": 100, "size_cm": [20, 4, 13], "size_spec": "20x4x13cm", "evidence": {"weight": "原文", "size": "原文"}, "confidence": 0.9}'
        )
        user_extract = "请抽取并换算以下商品采集数据：\n" + source_text

        extracted = self._call_llm(extract_config, system_extract, user_extract,
                                   self._validate_specs_extract, "extract")

        system_review = (
            "你是独立的数据审核 AI。必须只返回 JSON object。\n"
            "任务：审核另一 AI 从商品采集资料中抽取并换算的重量/尺寸是否正确。\n"
            "要求：\n"
            "1. 再次检查单位是否已经换算成 g 和 cm。\n"
            "2. 如果原结果错误，返回 corrected 后的 weight_g、size_cm、size_spec。\n"
            "3. approved 表示原结果是否可直接采用；即使 approved=false，也要给出你校正后的结构化结果。\n"
            '返回结构必须是：\n'
            '{"approved": true, "weight_g": 100, "size_cm": [20, 4, 13], "size_spec": "20x4x13cm", "evidence": {"weight": "原文", "size": "原文"}, "confidence": 0.9, "reason": "简短理由"}'
        )
        review_prompt = "商品采集资料：\n%s\n\n待审核抽取结果：\n%s" % (
            source_text, json.dumps(extracted, ensure_ascii=False, indent=2),
        )
        reviewed = self._call_llm(review_config, system_review, review_prompt,
                                  self._validate_specs_review, "review")

        # Re-fetch product to avoid stale data (read-modify-write race)
        product = self._find_product_or_raise(skc)
        product.set_collected_specs(
            weight_g=reviewed.get("weight_g", ""),
            size_spec=reviewed.get("size_spec", ""),
            size_cm=reviewed.get("size_cm", []),
            evidence=reviewed.get("evidence", {}),
            review={
                "approved": reviewed.get("approved"),
                "reason": reviewed.get("reason", ""),
                "extract_model": extracted.get("_model", ""),
                "review_model": reviewed.get("_model", ""),
                "extract_attempts": extracted.get("_attempts", 0),
                "review_attempts": reviewed.get("_attempts", 0),
                "confidence": reviewed.get("confidence", 0),
            },
        )
        self._product_repo.save(product)

        md = product.manual_data
        self._event_bus.publish_all(product.collect_events())
        return {
            "success": True,
            "skc": skc,
            "collected": {
                "weight_g": md.collected_weight_g,
                "size_spec": md.collected_size_spec,
                "size_cm": md.collected_size_cm,
                "evidence": md.collected_specs_evidence,
            },
            "review": md.collected_specs_review,
        }

    def auto_extract(self, skc: str) -> dict:
        product = self._find_product_or_raise(skc)
        pd = product.product_data
        attrs = pd.get("attributes", {})

        texts = [
            product.title,
            pd.get("about_item", ""),
            pd.get("product_description", ""),
            pd.get("description", ""),
            pd.get("title", ""),
        ]
        search_text = " ".join(t for t in texts if t)

        result = {}

        # Weight
        weight = attrs.get("weight") or attrs.get("重量") or ""
        if not weight:
            m = re.search(r'(\d+\.?\d*)\s*(?:g|克|gram)', search_text, re.IGNORECASE)
            if m:
                weight = m.group(1)
        result["weight_g"] = weight

        # Size
        size_raw = attrs.get("size") or attrs.get("尺寸") or attrs.get("dimensions") or ""
        length_cm, width_cm, height_cm = "", "", ""
        if not size_raw:
            m = re.search(r'(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*(?:cm|厘米|mm|毫米)?', search_text)
            if m:
                length_cm, width_cm, height_cm = m.group(1), m.group(2), m.group(3)
            else:
                m = re.search(r'尺寸[：:]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)', search_text)
                if m:
                    length_cm, width_cm, height_cm = m.group(1), m.group(2), m.group(3)
        else:
            m = re.search(r'(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)\s*[×xX*]\s*(\d+\.?\d*)', size_raw)
            if m:
                length_cm, width_cm, height_cm = m.group(1), m.group(2), m.group(3)
        result["length_cm"] = length_cm
        result["width_cm"] = width_cm
        result["height_cm"] = height_cm

        # Color
        color = attrs.get("color") or attrs.get("颜色") or ""
        if not color:
            color_keywords = [
                "black", "white", "red", "blue", "green", "yellow", "pink", "purple",
                "orange", "brown", "gray", "grey", "gold", "silver", "beige", "cream",
                "navy", "khaki", "camel", "coffee", "chocolate", "rose", "wine",
                "黑色", "白色", "红色", "蓝色", "绿色", "黄色", "粉色", "紫色",
                "橙色", "棕色", "灰色", "金色", "银色", "米色", "卡其", "咖啡",
                "深棕", "浅棕", "深蓝", "浅蓝", "深灰", "浅灰", "玫瑰", "酒红",
            ]
            found_colors = [c for c in color_keywords if c in search_text.lower()]
            if found_colors:
                color = ", ".join(found_colors[:3])
        result["color"] = color

        # Material
        material = attrs.get("material") or attrs.get("材质") or ""
        if not material:
            material_keywords = [
                "leather", "genuine leather", "pu leather", "synthetic leather",
                "fabric", "cotton", "polyester", "nylon", "canvas", "silk",
                "wool", "linen", "velvet", "suede", "mesh", "rubber",
                "plastic", "metal", "stainless steel", "alloy", "wood",
                "皮革", "真皮", "pu皮", "合成革", "布料", "棉", "涤纶",
                "尼龙", "帆布", "丝绸", "羊毛", "亚麻", "天鹅绒", "麂皮",
                "橡胶", "塑料", "金属", "不锈钢", "合金", "木质",
            ]
            found_materials = [m for m in material_keywords if m in search_text.lower()]
            if found_materials:
                material = ", ".join(found_materials[:3])
        result["material"] = material

        product.mark_auto_extracted(list(result.keys()))
        self._event_bus.publish_all(product.collect_events())

        return {"success": True, "skc": skc, "extracted": result}

    def extract_from_text(self, text: str) -> dict:
        if not text or not text.strip():
            raise ValueError("文本不能为空")

        config = self._get_llm_config("product_text_extract", "DEEPSEEK_TEXT_EXTRACT_MODEL", "deepseek-v4-pro")

        system_prompt = (
            "你是一个产品信息提取助手。请从用户提供的产品描述文本中提取三个字段，并**全部转换为国际单位**。\n\n"
            "提取规则：\n"
            "1. weight_g：提取产品的重量，**统一转换为克(g)**。例如 \"0.5kg\" → \"500\"，\"1.2 pounds\" → \"544\"，\"200g\" → \"200\"。只返回数字，不要单位。\n"
            "2. size_spec：提取产品的尺寸规格，**统一转换为厘米(cm)**，格式为 \"长×宽×高cm\"。例如 \"10x5x2 inches\" → \"25.4×12.7×5.1cm\"，\"20×10×3cm\" → \"20×10×3cm\"。如果只有两个维度也按此格式。\n"
            "3. spec：提取产品的规格描述，如颜色、尺码、型号、款式等变体信息。例如 \"黑色/大号\"、\"红色 S码\"。\n\n"
            "如果某个字段无法从文本中提取，返回空字符串。\n\n"
            '请严格按照以下 JSON 格式返回，不要包含其他内容：\n'
            '{"weight_g": "", "size_spec": "", "spec": ""}'
        )

        payload = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
        }
        if "v4-pro" in str(config["model"]).lower():
            payload["enable_thinking"] = False

        resp = requests.post(
            config["base_url"],
            headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"DeepSeek API Error {resp.status_code}: {resp.text[:300]}")

        result = resp.json()
        response_text = ""
        choices = result.get("choices", [])
        if choices:
            response_text = choices[0].get("message", {}).get("content", "")
        if not response_text:
            raise RuntimeError("模型未返回文本")

        json_match = re.search(r'\{[^{}]*\}', response_text)
        if json_match:
            extracted = json.loads(json_match.group())
        else:
            extracted = {"weight_g": "", "size_spec": "", "spec": ""}

        return {
            "success": True,
            "extracted": {
                "weight_g": extracted.get("weight_g", ""),
                "size_spec": extracted.get("size_spec", ""),
                "spec": extracted.get("spec", ""),
            },
        }

    # ==================== Images ====================

    def get_images(self, skc: str) -> dict:
        product = self._find_product_or_raise(skc)
        images = []
        image_sets_data = []
        seen_urls = set()

        pd = product.product_data
        images_dir = product.images_dir

        # 1. Local images from images_dir
        if images_dir and os.path.exists(images_dir):
            set_map = {}
            for root, _dirs, files in os.walk(images_dir):
                for fname in sorted(files):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in IMAGE_EXTENSIONS:
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, images_dir).replace("\\", "/")
                        parts = rel.split("/")
                        set_name = parts[0] if len(parts) > 1 else ""
                        img = {
                            "source": "local",
                            "local_path": full,
                            "url": f"/product_images/{skc}/{rel}",
                            "order": len(images),
                        }
                        images.append(img)
                        if set_name:
                            set_map.setdefault(set_name, []).append(img)
            for set_name in sorted(set_map):
                imgs = set_map[set_name]
                label = re.sub(r'^\d+_', '', set_name)
                image_sets_data.append({
                    "name": set_name,
                    "label": f"{label} ({len(imgs)}张)",
                    "images": imgs,
                })

        # 2. Remote URLs from product_data (only if no local images)
        if not images:
            top_images = pd.get("images", [])
            if isinstance(top_images, list) and top_images:
                proxy_imgs = []
                for url in top_images:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        img = {"source": "url", "url": f"/api/img_proxy?url={quote(url, safe='')}", "order": len(images)}
                        images.append(img)
                        proxy_imgs.append(img)
                if proxy_imgs:
                    image_sets_data.append({"name": "", "label": f"图片 ({len(proxy_imgs)}张)", "images": proxy_imgs})

            variant_data = pd.get("variantData", [])
            if isinstance(variant_data, list):
                for v in variant_data:
                    v_imgs = v.get("images", []) if isinstance(v, dict) else []
                    if not v_imgs:
                        continue
                    vname = v.get("variantName", "") if isinstance(v, dict) else ""
                    set_imgs = []
                    for url in v_imgs:
                        if url not in seen_urls:
                            seen_urls.add(url)
                            img = {"source": "url", "url": f"/api/img_proxy?url={quote(url, safe='')}", "order": len(images)}
                            images.append(img)
                            set_imgs.append(img)
                    if set_imgs:
                        image_sets_data.append({
                            "name": vname,
                            "label": f"{vname} ({len(set_imgs)}张)" if vname else f"变体 ({len(set_imgs)}张)",
                            "images": set_imgs,
                        })

        return {"success": True, "skc": skc, "images": images, "image_sets": image_sets_data}

    def get_image_sets(self, skc: str) -> dict:
        product = self._find_product_or_raise(skc)

        if product._image_sets:
            # Ensure image_subsets exists
            subsets = product._image_subsets if hasattr(product, '_image_subsets') else {}
            return {
                "success": True,
                "skc": skc,
                "image_sets": product.image_sets,
                "image_subsets": subsets,
            }

        # Auto-generate image_sets from images_dir
        images_dir = product.images_dir
        root_files = []
        subdir_sets = {}
        pd = product.product_data
        new_sets = {}

        if images_dir and os.path.exists(images_dir):
            for root, _dirs, files in os.walk(images_dir):
                rel = os.path.relpath(root, images_dir)
                if rel == ".":
                    for fname in sorted(files):
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in IMAGE_EXTENSIONS:
                            root_files.append({"filename": fname, "index": len(root_files)})
                else:
                    set_name = re.sub(r'^\d+_', '', rel.replace("\\", "/"))
                    sdir_entries = []
                    for fname in sorted(files):
                        ext = os.path.splitext(fname)[1].lower()
                        if ext in IMAGE_EXTENSIONS:
                            sdir_entries.append({"filename": os.path.join(rel, fname).replace("\\", "/"), "index": len(sdir_entries)})
                    if sdir_entries:
                        subdir_sets[set_name] = sdir_entries

        # Remote URLs supplement
        all_local_fns = set()
        for e in root_files:
            all_local_fns.add(e["filename"])
        for entries in subdir_sets.values():
            for e in entries:
                all_local_fns.add(os.path.basename(e["filename"]))

        image_urls = pd.get("images", [])
        for url in image_urls:
            url_basename = url.split("/")[-1].split("?")[0]
            if len(url_basename) < 10:
                continue
            if not any(url_basename.split(".")[0][:15] in fn for fn in all_local_fns):
                root_files.append({"url": url, "filename": "", "index": len(root_files)})

        if root_files:
            new_sets["采集图片"] = root_files

        variant_data = pd.get("variantData", [])
        if isinstance(variant_data, list):
            for v in variant_data:
                vname = v.get("variantName", "") if isinstance(v, dict) else ""
                if not vname:
                    continue
                v_imgs = v.get("images", []) if isinstance(v, dict) else []
                if not v_imgs:
                    continue
                if vname in subdir_sets:
                    continue
                variant_set = []
                for vi, url in enumerate(v_imgs):
                    variant_set.append({"url": url, "filename": "", "index": vi})
                if variant_set:
                    subdir_sets[vname] = variant_set

        for sname, entries in subdir_sets.items():
            new_sets[sname] = entries

        product.update_image_sets(new_sets)
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())

        return {
            "success": True,
            "skc": skc,
            "image_sets": product.image_sets,
            "image_subsets": product._image_subsets,
        }

    def update_image_sets(self, skc: str, data: dict) -> dict:
        product = self._find_product_or_raise(skc)
        new_sets = data.get("image_sets", {})
        new_subsets = data.get("image_subsets", {})

        product.update_image_sets(new_sets, new_subsets)

        # Collect referenced files
        referenced = set()
        referenced_basenames = set()
        for entries in product._image_sets.values():
            for entry in entries:
                fn = entry.get("filename", "")
                if fn:
                    referenced.add(fn)
                    referenced_basenames.add(os.path.basename(fn))
        for set_subs in product._image_subsets.values():
            for entries in set_subs.values():
                for entry in entries:
                    fn = entry.get("filename", "")
                    if fn:
                        referenced.add(fn)
                        referenced_basenames.add(os.path.basename(fn))

        # Delete unreferenced physical files
        images_dir = product.images_dir
        deleted_count = 0
        if images_dir and os.path.exists(images_dir):
            for root, _dirs, files in os.walk(images_dir, topdown=False):
                for fname in files:
                    if os.path.splitext(fname)[1].lower() in IMAGE_EXTENSIONS:
                        rel = os.path.relpath(os.path.join(root, fname), images_dir).replace("\\", "/")
                        if rel not in referenced and fname not in referenced_basenames:
                            try:
                                os.remove(os.path.join(root, fname))
                                deleted_count += 1
                            except OSError:
                                logger.warning(f"删除图片文件失败: {rel}")
                if root != images_dir:
                    try:
                        remaining = [f for f in os.listdir(root) if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS]
                        if not remaining:
                            os.rmdir(root)
                    except OSError:
                        pass

        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())
        return {"success": True, "deleted_files": deleted_count}

    def upload_image(self, skc: str, file) -> dict:
        """上传图片到产品目录。file 是 Flask FileStorage 对象。"""
        from werkzeug.utils import secure_filename

        product = self._find_product_or_raise(skc)
        images_dir = product.images_dir
        if not images_dir or not os.path.exists(images_dir):
            raise ValueError("产品图片目录不存在")

        set_name = getattr(file, "set_name", None)
        if not set_name and hasattr(file, "form"):
            set_name = file.form.get("set_name", "采集图片")
        if not set_name:
            set_name = "采集图片"
        sub_name = getattr(file, "sub_name", "") or ""

        safe_name = secure_filename(file.filename)
        if set_name == "采集图片":
            dest_dir = images_dir
            rel_name = safe_name
        else:
            dest_dir = os.path.join(images_dir, set_name)
            os.makedirs(dest_dir, exist_ok=True)
            rel_name = f"{set_name}/{safe_name}"

        filepath = os.path.join(dest_dir, safe_name)
        file.save(filepath)

        if sub_name:
            subsets = dict(product._image_subsets or {})
            set_subsets = dict(subsets.get(set_name, {}) or {})
            entries = list(set_subsets.get(sub_name, []) or [])
            entry = {"filename": rel_name, "index": len(entries)}
            entries.append(entry)
            set_subsets[sub_name] = entries
            subsets[set_name] = set_subsets
            product.update_image_sets(product.image_sets, subsets)
        else:
            product.add_image_to_set(set_name, {"filename": rel_name})
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())

        return {
            "success": True,
            "entry": entry if sub_name else {"filename": rel_name, "index": len(product._image_sets.get(set_name, [])) - 1},
            "url": f"/product_images/{skc}/{rel_name}",
        }

    def upload_video(self, skc: str, file) -> dict:
        from werkzeug.utils import secure_filename

        safe_name = secure_filename(file.filename)
        dest_dir = os.path.join(self._videos_dir, skc)
        os.makedirs(dest_dir, exist_ok=True)
        filepath = os.path.join(dest_dir, safe_name)
        file.save(filepath)

        # Update product video_url if product exists
        try:
            product = self._find_product_or_raise(skc)
            product.set_video_url(f"/videos/{skc}/{safe_name}")
            self._product_repo.save(product)
            self._event_bus.publish(ProductVideoUploaded(skc=skc, filename=safe_name))
        except Exception:
            pass  # Allow video upload even if product doesn't exist yet

        return {
            "success": True,
            "filename": safe_name,
            "url": f"/videos/{skc}/{safe_name}",
        }

    def proxy_image(self, url: str) -> bytes:
        """Proxy external images, returns raw bytes (Flask route handles response)."""
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        if domain not in _IMG_PROXY_ALLOWED:
            raise ValueError(f"Domain not allowed for proxy: {domain}")

        referer_map = {
            "amazon": "https://www.amazon.com/",
            "alicdn": "https://detail.1688.com/",
            "wildberries": "https://www.wildberries.ru/",
            "ozon": "https://www.ozon.ru/",
        }
        referer = "https://www.amazon.com/"
        for key, ref in referer_map.items():
            if key in domain:
                referer = ref
                break

        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": referer,
        }, timeout=15)
        if resp.status_code == 200:
            return resp.content
        raise RuntimeError("Image proxy request failed")

    # ==================== 关键属性审批 ====================

    def propose_critical_change(self, skc: str, field: str, new_value,
                                requested_by: str) -> dict:
        """提交关键属性修改申请，返回 approval_id"""
        product = self._find_product_or_raise(skc)
        approval_id = product.propose_change(field, new_value, requested_by)
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())
        return {"success": True, "skc": skc, "approval_id": approval_id}

    def approve_change(self, skc: str, approval_id: str,
                       approved_by: str) -> dict:
        """审批通过，应用修改"""
        product = self._find_product_or_raise(skc)
        product.approve_change(approval_id, approved_by)
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())
        return {"success": True, "skc": skc, "approval_id": approval_id}

    def reject_change(self, skc: str, approval_id: str,
                      approved_by: str, reason: str) -> dict:
        """驳回修改"""
        product = self._find_product_or_raise(skc)
        product.reject_change(approval_id, approved_by, reason)
        self._product_repo.save(product)
        self._event_bus.publish_all(product.collect_events())
        return {"success": True, "skc": skc, "approval_id": approval_id}

    def list_pending_approvals(self, skc: str = None) -> list[dict]:
        """查询待审批列表：指定 skc 则返回该产品的，否则返回全部产品的"""
        if skc:
            product = self._find_product_or_raise(skc)
            return product.pending_approvals
        collection = self._product_repo.load_all()
        results = []
        for product in collection.products:
            for approval in product.pending_approvals:
                results.append({
                    "skc": product.skc,
                    **approval,
                })
        return results

    # ==================== Helper ====================

    def _find_product_or_raise(self, skc: str) -> Product:
        product = self._product_repo.find_by_id(skc)
        if not product:
            raise ValueError("产品不存在")
        return product
