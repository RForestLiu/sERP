"""
Listing 域 - DeepSeek AI 自动填充客户端。
"""
from __future__ import annotations

import json as _json
import logging
import re
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from ..domain.services import (
    COMMON_ATTRIBUTE_PRESETS,
    NON_REQUIRED_COMMON_ATTR_MAP,
    AttributePresetMatcher,
    DeterministicPreFiller,
)

logger = logging.getLogger(__name__)


class DeepSeekAutoFillClient:
    """DeepSeek AI 自动填充客户端 — 封装 HTTP 调用和 prompt 管理"""

    def __init__(self, base_url: str, api_key: str, model: str = "deepseek-v4-flash"):
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    @classmethod
    def resolve(cls, settings_facade, feature_key: str = "ozon_attribute_fill") -> "DeepSeekAutoFillClient":
        """从 SettingsFacade 解析配置并创建实例"""
        import os as _os
        base_url = _os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        api_key = _os.getenv("DEEPSEEK_API_KEY", "")
        model = _os.getenv("DEEPSEEK_AUTO_FILL_MODEL", "deepseek-v4-pro")

        try:
            model_id = settings_facade.get_feature_model(feature_key)
            models = settings_facade.get_models()
            for m in models:
                if m.get("id") == model_id:
                    base_url = m.get("base_url") or base_url
                    model = m.get("model") or model
                    api_key_env = m.get("api_key_env") or "DEEPSEEK_API_KEY"
                    api_key = _os.getenv(api_key_env, api_key)
                    break
        except Exception:
            pass

        return cls(base_url=base_url, api_key=api_key, model=model)

    # ── 店小秘自动填充 ──

    def analyze_dianxiaomi(
        self,
        skc: str,
        product_title: str,
        product_data: dict,
        manual_data: dict,
        form_fields: list[dict],
        custom_prompts: dict,
        variant_list: list[dict],
        variant_row_summary: dict,
    ) -> list[dict]:
        # 构建产品信息摘要
        attrs = product_data.get("attributes", {})
        about_item = product_data.get("about_item", "")
        product_description = product_data.get("product_description", "")
        description = product_data.get("description", "")
        product_details = product_data.get("product_details", {})
        if product_details and isinstance(product_details, dict) and product_details.get("_raw"):
            del product_details["_raw"]
        brand = product_data.get("brand", "")
        category = product_data.get("category", "")
        rating = product_data.get("rating", "")

        # 单位换算提示
        unit_hints = self._build_unit_hints(product_details, attrs)
        product_texts = [
            "品牌: " + brand if brand else "",
            "品类: " + category if category else "",
            "评分: " + rating if rating else "",
            product_title,
            about_item,
            product_description,
            description,
            ("### 单位换算提醒（重点关注以下字段）\n" + "\n".join(unit_hints)) if unit_hints else "",
            "### 产品规格 (含原始单位，填充时注意换算)\n" + _json.dumps(product_details, ensure_ascii=False, indent=2) if product_details else "",
        ]

        # 变体信息
        if variant_list:
            variant_text = "### 变体列表（结构化）\n"
            for i, v in enumerate(variant_list):
                variant_text += f"  变体{i+1}: 名称={v.get('name','')}, 价格={v.get('price','')}, "
                variant_text += f"库存={v.get('stock','')}, 属性={_json.dumps(v.get('attributes',{}), ensure_ascii=False)}\n"
            product_texts.append(variant_text)
        else:
            variants_fb = product_data.get("variants", {})
            if variants_fb and variants_fb.get("values"):
                variant_text = "### 变体信息\n" + _json.dumps(variants_fb, ensure_ascii=False, indent=2)
                product_texts.append(variant_text)

        # 确定性数据提示
        deterministic_hints = DeterministicPreFiller.extract(manual_data, product_data)
        hints_text = ""
        if deterministic_hints:
            hints_lines = [f"  - {k}: {v}" for k, v in deterministic_hints.items()]
            hints_text = "\n### 已知确定数据（优先使用）\n" + "\n".join(hints_lines)

        product_text = "\n".join(t for t in product_texts if t)

        # 表单字段摘要
        full_product_data_text = _json.dumps(product_data, ensure_ascii=False, indent=2)
        fields_text, field_by_index, valid_field_indices = self._build_form_fields_summary(form_fields)

        # System prompt
        system_prompt = self._dianxiaomi_system_prompt(custom_prompts)

        # 变体行映射
        variant_summary_block = self._build_variant_summary_block(variant_row_summary)

        user_prompt = f"""## 产品信息
SKC: {skc}
标题: {product_title}

### 产品描述文本
{product_text[:3000]}
### 完整产品数据
{full_product_data_text}
{hints_text}
### 人工登记数据
{_json.dumps(manual_data, ensure_ascii=False, indent=2)}
{variant_summary_block}
### 表单字段列表（共 {len(form_fields)} 个字段）
{fields_text}

请分析以上表单字段，为每个字段提供填充值。"""

        # 双批次并行
        important_fields, regular_fields = self._split_important_fields(form_fields)

        def _call(label: str, sys_prompt: str, usr_prompt: str) -> list[dict]:
            return self._api_call(sys_prompt, usr_prompt, label=label)

        def _build_regular_system_prompt() -> str:
            return """你是电商产品表单填充助手，负责填充常规属性字段。

## 规则
1. select/checkbox-group/radio-group：从可选值中精确选取
2. 材质/颜色：根据产品数据填充
3. 重量/尺寸：填纯数字不含单位，优先用人工登记数据
4. 不确定的字段留空，不编造

返回 JSON: {"mappings": [{"index": <序号>, "value": "填充值"}, ...]}"""

        all_mappings: list[dict] = []
        try:
            if important_fields and regular_fields:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future_imp = executor.submit(_call, "important", system_prompt, user_prompt)
                    future_reg = executor.submit(_call, "regular", _build_regular_system_prompt(), user_prompt)
                    try:
                        all_mappings.extend(future_imp.result(timeout=150))
                    except Exception as e:
                        logger.warning("[auto-fill] important batch failed: %s", e)
                    try:
                        all_mappings.extend(future_reg.result(timeout=150))
                    except Exception as e:
                        logger.warning("[auto-fill] regular batch failed: %s", e)

            if not all_mappings:
                all_mappings = _call("unified", system_prompt, user_prompt)
        except Exception:
            return []

        # 去重
        deduped: list[dict] = []
        seen: set[int] = set()
        for m in all_mappings:
            idx = m.get("index")
            if idx in seen:
                continue
            seen.add(idx)
            deduped.append(m)
        return deduped

    # ── Ozon 属性填充 ──

    def fill_ozon_attributes(
        self,
        skc: str,
        product_title: str,
        product_data: dict,
        manual_data: dict,
        ozon_attributes: list[dict],
    ) -> dict:
        # 匹配预设
        preset_map, non_required_presets = AttributePresetMatcher.match(ozon_attributes)
        deterministic_hints = DeterministicPreFiller.extract(manual_data, product_data)

        about_item = product_data.get("about_item", "")
        product_description = product_data.get("product_description", "")
        description_text = product_data.get("description", "")
        product_details = product_data.get("product_details", {})
        if product_details and isinstance(product_details, dict) and product_details.get("_raw"):
            product_details = dict(product_details)
            del product_details["_raw"]
        product_texts = [product_title, about_item, product_description, description_text]
        if product_details:
            product_texts.append("### 产品规格\n" + _json.dumps(product_details, ensure_ascii=False, indent=2))
        product_text = "\n".join(t for t in product_texts if t)
        full_product_data_text = _json.dumps(product_data, ensure_ascii=False, indent=2)

        # 拆分重要/常规属性
        important_attrs, regular_attrs = self._split_ozon_attrs(ozon_attributes)

        hints_text = ""
        if deterministic_hints:
            hints_lines = [f"  - {k}: {v}" for k, v in deterministic_hints.items()]
            hints_text = "\n### 已知确定数据（优先使用）\n" + "\n".join(hints_lines)

        # 构建正则批次 prompt
        hints_text += "\n数据优先级：manual_data 优先级高于采集数据；manual_data 为空时才使用 product_details / product_data 中采集到的数据。"

        def _build_regular_batch():
            reg_summary = self._build_ozon_attr_summary(regular_attrs, preset_map)
            reg_system = """你是俄罗斯电商平台（Ozon/Wildberries）属性填充专家。

## 规则
1. dictionary类型：从可选值中精确选取
2. 材质/颜色：翻译为俄语，dictionary则从列表中选
3. 重量/尺寸：填纯数字不含单位，优先用人工登记数据
4. 原产国：默认"Китай"
5. 不确定的字段留空，不编造

返回 JSON: {"mappings": [{"attribute_id": 123, "value": "填充值"}, ...]}"""
            reg_user = f"""## 产品信息
SKC: {skc}
标题: {product_title}
产品文本: {product_text[:3000]}
### 完整产品数据
{full_product_data_text}
{hints_text}
人工登记: {_json.dumps(manual_data, ensure_ascii=False, indent=2)}

## 常规属性列表（共 {len(regular_attrs)} 个）
{chr(10).join(reg_summary)}

请为以上每个属性提供填充值。"""
            return self._api_call_attr(reg_system, reg_user, label="常规属性")

        # 构建重要批次 prompt
        def _build_important_batch():
            imp_summary = self._build_ozon_attr_summary(important_attrs, preset_map, important=True)
            imp_system = self._ozon_important_system_prompt()
            imp_user = f"""## 产品信息
SKC: {skc}
标题: {product_title}
产品文本: {product_text[:3000]}
### 完整产品数据
{full_product_data_text}
{hints_text}
人工登记: {_json.dumps(manual_data, ensure_ascii=False, indent=2)}

## 重要属性列表（共 {len(important_attrs)} 个）
{chr(10).join(imp_summary)}

请为以上每个属性提供填充值。"""
            return self._api_call_attr(imp_system, imp_user, label="重要属性")

        all_mappings: list[dict] = []
        important_count = 0
        regular_count = 0

        if important_attrs and regular_attrs:
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_imp = executor.submit(_build_important_batch)
                future_reg = executor.submit(_build_regular_batch)
                try:
                    batch1 = future_imp.result(timeout=150)
                    all_mappings.extend(batch1)
                    important_count = len(batch1)
                except Exception as e:
                    logger.warning("[自动填充] 重要属性批次失败: %s", e)
                try:
                    batch2 = future_reg.result(timeout=150)
                    all_mappings.extend(batch2)
                    regular_count = len(batch2)
                except Exception as e:
                    logger.warning("[自动填充] 常规属性批次失败: %s", e)
        elif important_attrs:
            batch1 = _build_important_batch()
            all_mappings.extend(batch1)
            important_count = len(batch1)
        elif regular_attrs:
            batch2 = _build_regular_batch()
            all_mappings.extend(batch2)
            regular_count = len(batch2)

        return {
            "success": True,
            "skc": skc,
            "mappings": all_mappings,
            "total_attributes": len(ozon_attributes),
            "filled_attributes": len(all_mappings),
            "important_count": len(important_attrs),
            "regular_count": len(regular_attrs),
            "preset_matched": len(preset_map),
            "non_required_presets": len(non_required_presets),
            "deterministic_hints": list(deterministic_hints.keys()),
        }

    # ==================== 内部辅助 ====================

    def _api_call(self, sys_prompt: str, usr_prompt: str, label: str = "fill", model: str | None = None) -> list[dict]:
        """调用 DeepSeek 并解析返回的 mappings（店小秘格式，index-based）"""
        model = model or self._model
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
        }
        if model == "deepseek-v4-pro":
            payload["thinking"] = {"type": "disabled"}

        try:
            resp = requests.post(
                self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            if resp.status_code != 200:
                logger.warning("[auto-fill/%s] API Error %s: %s", label, resp.status_code, resp.text[:500])
                return []
            result = resp.json()
            choices = result.get("choices", [])
            if not choices:
                return []
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or msg.get("reasoning_content", "")
            if not text:
                return []

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start:end + 1]

            parsed = _json.loads(cleaned)
            mappings = parsed.get("mappings", [])
            if not isinstance(mappings, list):
                return self._retry(sys_prompt, usr_prompt, label, model)
            return [{"index": m.get("index"), "label": m.get("label", ""), "value": str(m.get("value", ""))}
                    for m in mappings if isinstance(m, dict) and m.get("value")]
        except _json.JSONDecodeError:
            logger.warning("[auto-fill/%s] JSON 解析失败", label)
            return self._retry(sys_prompt, usr_prompt, label, model)
        except Exception as e:
            logger.error("[auto-fill/%s] 异常: %s", label, e)
            return []

    def _retry(self, sys_prompt: str, usr_prompt: str, label: str, model: str) -> list[dict]:
        if "retry" in label:
            return []
        retry_user = usr_prompt + "\n\n上一次返回不是合法 JSON 或 mappings 不是数组。请只返回 JSON：{\"mappings\":[{\"index\":0,\"value\":\"...\"}]}"
        return self._api_call(sys_prompt, retry_user, label + ":retry", model)

    def _api_call_attr(self, sys_prompt: str, usr_prompt: str, label: str = "fill") -> list[dict]:
        """调用 DeepSeek 并解析返回的 mappings（Ozon 属性格式，attribute_id-based）"""
        model = "deepseek-v4-pro"
        evidence_instruction = (
            '\n\nReturn JSON only. Every mapping must include "evidence": '
            'a short quote or concrete product-data source that supports the value.'
        )
        if '"evidence"' not in sys_prompt:
            sys_prompt += evidence_instruction
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": usr_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }

        try:
            resp = requests.post(
                self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )
            if resp.status_code != 200:
                logger.warning("[自动填充/%s] API Error %s: %s", label, resp.status_code, resp.text[:500])
                return []
            result = resp.json()
            choices = result.get("choices", [])
            if not choices:
                return []
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or msg.get("reasoning_content", "")
            if not text:
                return []

            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start:end + 1]

            parsed = _json.loads(cleaned)
            mappings = parsed.get("mappings", [])
            validated: list[dict] = []
            for m in mappings:
                if isinstance(m, dict) and "attribute_id" in m:
                    item = {
                        "attribute_id": m.get("attribute_id"),
                        "value": str(m.get("value", "")),
                    }
                    if m.get("dictionary_value_id"):
                        item["dictionary_value_id"] = m.get("dictionary_value_id")
                    if isinstance(m.get("values"), list):
                        item["values"] = m.get("values")
                    if m.get("confidence") is not None:
                        item["confidence"] = m.get("confidence")
                    if m.get("needs_review") is not None:
                        item["needs_review"] = m.get("needs_review")
                    if m.get("reason"):
                        item["reason"] = str(m.get("reason"))
                    if m.get("evidence"):
                        item["evidence"] = m.get("evidence")
                    validated.append(item)
            logger.info("[自动填充/%s] 填充 %s 个属性", label, len(validated))
            return validated
        except _json.JSONDecodeError:
            logger.warning("[自动填充/%s] JSON 解析失败", label)
            return []
        except Exception as e:
            logger.error("[自动填充/%s] 异常: %s", label, e)
            return []

    @staticmethod
    def _build_unit_hints(product_details: dict, attrs: dict) -> list[str]:
        unit_hints: list[str] = []
        if product_details and isinstance(product_details, dict):
            weight_keys = [k for k in product_details if any(w in k.lower() for w in ["weight", "重量", "вес", "масса"])]
            dim_keys = [k for k in product_details if any(d in k.lower() for d in ["dimension", "size", "размер", "尺寸", "length", "長", "width", "寬", "height", "高", "depth", "深"])]
            for k in (weight_keys + dim_keys)[:8]:
                val = product_details[k]
                if val and isinstance(val, str):
                    val_lower = val.lower()
                    hint = f"  - {k}: {val}"
                    if any(u in val_lower for u in ["oz", "ounce", "盎司", "lb", "pound", "磅"]):
                        hint += " → 需换算为克(g): 1oz≈28.35g, 1lb≈453.6g"
                    elif any(u in val_lower for u in ["in", "inch", "英寸", '"', "ft", "feet", "英尺"]):
                        hint += " → 需换算为厘米(cm): 1in≈2.54cm"
                    unit_hints.append(hint)
            if attrs and isinstance(attrs, dict):
                for k, v in attrs.items():
                    if isinstance(v, str) and any(u in v.lower() for u in ["oz", "lb", "in", "inch", "pound", "ounce"]):
                        unit_hints.append(f"  - {k}: {v} → 注意单位换算")
        return unit_hints

    @staticmethod
    def _build_form_fields_summary(form_fields: list[dict]) -> tuple[str, dict, set]:
        fields_summary: list[str] = []
        field_by_index: dict[int, dict] = {}
        valid_indices: set[int] = set()
        for i, f in enumerate(form_fields):
            label = f.get("label", "")
            placeholder = f.get("placeholder", "")
            tag = f.get("tag", "")
            ftype = f.get("type", "")
            name = f.get("name", "")
            options = f.get("options", [])
            fidx = f.get("index", i)
            try:
                idx = int(fidx)
            except (TypeError, ValueError):
                idx = i
            valid_indices.add(idx)
            field_desc = f"  [{idx}] 标签: {label or name or '(无标签)'}"
            if placeholder:
                field_desc += f" | 占位: {placeholder}"
            dxm_attr = f.get("dxmAttribute") or {}
            if isinstance(dxm_attr, dict) and dxm_attr.get("attributeId"):
                field_desc += (
                    f" | DXM属性ID: {dxm_attr.get('attributeId')}"
                    f" | DXM控件: {dxm_attr.get('dxmControlKind') or ''}"
                    f" | 字典ID: {dxm_attr.get('dictionaryId') or '0'}"
                    f" | 多值: {dxm_attr.get('collection')}"
                    f" | 必填: {dxm_attr.get('required')}"
                )
                if dxm_attr.get("name") or dxm_attr.get("nameCn"):
                    field_desc += f" | DXM名称: {dxm_attr.get('nameCn') or ''}/{dxm_attr.get('name') or ''}"
            if options:
                option_texts: list[str] = []
                for o in options[:30]:
                    if isinstance(o, dict):
                        option_texts.append(o.get("text") or o.get("value") or "")
                    else:
                        option_texts.append(str(o))
                option_texts = [t for t in option_texts if t]
                if option_texts:
                    field_desc += f" | 选项: {', '.join(option_texts)}"
            fields_summary.append(field_desc)
            field_by_index[idx] = f
        return "\n".join(fields_summary), field_by_index, valid_indices

    @staticmethod
    def _build_variant_summary_block(variant_row_summary: dict) -> str:
        if not variant_row_summary:
            return ""
        row_ctxs = variant_row_summary.get("row_contexts", [])
        vc = variant_row_summary.get("variant_count", 0)
        note = variant_row_summary.get("note", "")
        return f"""
### 变体行映射
表单SKU行上下文: {_json.dumps(row_ctxs, ensure_ascii=False)}
变体总数: {vc}
说明: {note}
"""

    @staticmethod
    def _split_important_fields(form_fields: list[dict]) -> tuple[list[dict], list[dict]]:
        IMPORTANT_KW = [
            "название", "наименование", "name", "title", "名称", "标题", "полное название",
            "название товара", "наименование товара",
            "описание", "description", "描述", "说明", "аннотация", "описание товара",
            "hashtag", "хэштег", "тег", "тэг", "标签", "метка", "поисковые теги",
            "ключевые слова", "theme_tags",
            "rich", "showcase", "json", "富文本", "контент", "описание в формате",
            "раShowcase", "витрина",
        ]
        important: list[dict] = []
        regular: list[dict] = []
        for f in form_fields:
            label = (f.get("label", "") + " " + f.get("placeholder", "")).lower()
            if any(kw in label for kw in IMPORTANT_KW):
                important.append(f)
            else:
                regular.append(f)
        return important, regular

    @staticmethod
    def _split_ozon_attrs(ozon_attributes: list[dict]) -> tuple[list[dict], list[dict]]:
        IMPORTANT_KW = [
            "название", "наименование", "name", "title", "名称", "标题", "полное название",
            "название товара", "наименование товара",
            "описание", "description", "描述", "说明", "аннотация", "описание товара",
            "hashtag", "хэштег", "тег", "тэг", "标签", "метка", "поисковые теги",
            "ключевые слова", "theme_tags",
            "rich", "showcase", "json", "富文本", "контент", "описание в формате",
            "раShowcase", "витрина",
        ]
        important: list[dict] = []
        regular: list[dict] = []
        for attr in ozon_attributes:
            name_text = f"{attr.get('name', '')} {attr.get('name_cn', '')}".lower()
            if any(kw in name_text for kw in IMPORTANT_KW):
                important.append(attr)
            else:
                regular.append(attr)
        return important, regular

    @staticmethod
    def _build_ozon_attr_summary(attrs: list[dict], preset_map: dict, important: bool = False) -> list[str]:
        summary: list[str] = []
        for attr in attrs:
            label = f"ID:{attr.get('id')} 名称:{attr.get('name')}"
            cn = attr.get('name_cn', '')
            if cn:
                label += f"（{cn}）"
            label += f" 类型:{attr.get('type')} {'🔴必填' if attr.get('is_required') else '⚪选填'}"
            if attr.get("dictionary_values"):
                vals = [v.get("value", "") for v in attr["dictionary_values"][:30]]
                label += f" 可选值: [{', '.join(vals)}]"
            if attr.get("id") in preset_map:
                label += f"\n    📋 专用指引: {preset_map[attr.get('id')]}"
            summary.append(label)
        return summary

    def _dianxiaomi_system_prompt(self, custom_prompts: dict) -> str:
        prompt = """你是一个电商产品表单自动填充助手。你的任务是根据产品数据，为店小秘 Ozon 产品添加页面的表单字段提供填充值。

## 重要字段特殊规则
- 产品名称(название/name/title): 翻译为俄语，50-100字符，不包含品牌名，关键词前置
- 描述(описание/description): 4+1框架 —— 功能(1-2句) + 材质(1句) + 使用场景(1句) + 优势(1-2句) + 可选提示
- 标签(hashtag/хэштег): 生成10-22个标签，每个≤28字符，#开头，空格分隔。方法：核心词→长尾词→场景词→受众词→特征词
- 富文本(rich/json/showcase): 生成为raShowcase JSON格式

## 输入格式
你将收到：
1. 产品信息（标题、描述、属性等）
2. 表单字段列表（每个字段以 [序号] 开头，包含标签、占位符、选项等）
3. 变体列表 variant_list（结构化变体数据，含名称/价格/库存/属性）
4. 变体行映射 variant_row_summary（row_contexts 列表对应表单SKU行，variant_count 为应有变体数）
5. 表单字段标签可能包含 `[行上下文]`，用于区分多行SKU中相同名称的字段。

## SKU多行填充规则
- variant_row_summary 中的 row_contexts 列表按表单SKU行顺序排列（第0行→第1行→...）
- variant_list 的第i个变体对应表单的第i个SKU行
- 每个SKU行的字段标签都带 `[行上下文]` 后缀，根据行上下文匹配对应变体的属性
- 如果缺少某变体的特定数据，用产品级数据或推断填充

## 字段标签说明
- 普通文本字段：标签如 "产品名称"、"重量, г"
- **checkbox-group**（多选组）：标签格式为 "属性名 (可选值: 选项A / 选项B / 选项C)"，value 填应勾选的选项文本（多个用逗号分隔）。如果都不匹配则填 false
- **radio-group**（单选组）：标签格式为 "属性名 (选项: 选项A / 选项B / 选项C)"，value 填应选中的选项文本
- **select**（下拉框）：标签后可能包含 `| 选项: ...`，从选项列表中选取最接近的值

## 输出要求
请分析每个表单字段，判断它对应产品数据中的哪个信息，然后给出填充值。

### 字段匹配规则：
- **产品名称/标题** → 匹配标签含"名称""标题""name""title"的字段
- **产品描述** → 匹配标签含"描述""说明""description"的字段
- **价格** → 匹配标签含"价格""售价""price"的字段
- **重量** → 匹配标签含"重量""weight""重さ"的字段
- **尺寸/长宽高** → 匹配标签含"尺寸""长""宽""高""size""dimension"的字段
- **颜色** → 匹配标签含"颜色""color""colour"的字段
- **材质/材料** → 匹配标签含"材质""材料""material""leather"的字段
- **品牌** → 匹配标签含"品牌""brand"的字段
- **分类/品类** → 匹配标签含"分类""品类""category"的字段
- **数量/件数/个数** → 匹配标签含"数量""库存""件数""个数""quantity""count""pcs"的字段
- **对于 select 下拉框**：从选项列表中匹配最接近的值
- **对于 checkbox-group**：从"可选值"列表中选择匹配产品数据的选项文本
- **对于 radio-group**：从"选项"列表中选择最匹配产品数据的一个选项文本

### 重要规则：
1. index 必须是表单字段列表里对应字段的 **[序号]** 值，直接填数字
2. 尽量为每个字段提供填充值，能推断的就推断
3. 对于下拉框(select)和选项组(checkbox-group/radio-group)，必须从提供的选项列表中选取值
4. 所有值必须是字符串
5. 明显无关的字段可跳过，但属性类字段尽量填充

## 单位换算规则
- 重量: 1 oz ≈ 28.35g, 1 lb ≈ 453.6g, 1 kg = 1000g。一律填写克(g)的纯数值
- 尺寸: 1 in ≈ 2.54cm。一律填写厘米(cm)的纯数值
- 若字段标签/placeholder已含单位，只填数值不含单位
- 若产品规格已是公制，直接使用
- 优先使用 manual_data.effective_weight_g / effective_size_spec

请严格按照以下 JSON 格式返回：
{"mappings": [{"index": <序号>, "value": "..."}, ...]}

## Hard validation contract
- Fields whose label/tag/type contains JSON, rich, showcase, 富文本, raShowcase, or json-editor are JSON rich-text fields. Fill them with valid JSON only.
- Fields whose label contains 产品描述, 描述, 说明, description, описание, or аннотация are normal product-description fields unless they are explicitly JSON rich-text fields.
- Never put raShowcase/JSON rich-text content into a normal product-description field.
- If both a normal product-description field and a JSON rich-text field exist, produce two different values: prose for the description field, JSON for the JSON field.
"""
        if custom_prompts:
            parts = []
            for key, label in [
                ("title", "产品标题"), ("description", "产品描述"), ("json_text", "JSON文本"),
                ("hashtag", "主题标签"), ("platform", "平台"), ("store", "店铺"), ("category", "品类"),
            ]:
                if custom_prompts.get(key):
                    parts.append(f"### {label}填充提示\n{custom_prompts[key]}")
            if parts:
                prompt += "\n## 用户自定义填充提示\n" + "\n\n".join(parts) + "\n"
        return prompt

    @staticmethod
    def _ozon_important_system_prompt() -> str:
        return """你是俄罗斯电商平台（Ozon/Wildberries）的资深内容优化专家。

## 任务
你正在处理的是**重要属性**（标题/描述/标签/富文本），这些属性直接影响商品的搜索排名和转化率。

## 标题类属性填充规则
- 俄语撰写，50~100字符
- 结构：商品类型 + 关键特征（材质/功能） + 适用对象
- 严禁品牌名和特殊符号（™®×•·）
- 使用Ozon/WB平台高频搜索词

## 描述类属性填充规则（4+1框架）
- ① 功能用途 — 1~2句说明产品是什么、做什么
- ② 材质设计 — 材料、工艺、结构
- ③ 适用场景 — 什么人、什么场合
- ④ 优势特点 — 差异化卖点
- ⑤（可选）使用提示
- 客观语气，每段≤4句，俄语撰写

## 标签/Hashtag类属性填充规则（5步法）
- ① 提取核心词（材质、功能、规格）
- ② 对齐Ozon高频搜索词
- ③ 分组排序：功能类 > 用户群体类 > 场景类 > 节日类(可选)
- ④ 每个标签≤28字符，#开头，不含品牌
- ⑤ 10~22个标签，一行空格分隔
- 节日标签：仅距离节日≤2个月且产品适合送礼时加1-3个

## 富文本/JSON类属性填充规则
- 如属性为raShowcase JSON格式，生成标准 {"version": 0.3, "content": [...]} 结构
- 所有文字俄语，自然流畅

## 通用约束
- dictionary类型必须从可选值中精确选取
- 不确定的字段可留空，不编造
- 返回 JSON: {"mappings": [{"attribute_id": 123, "value": "填充值"}, ...]}"""
