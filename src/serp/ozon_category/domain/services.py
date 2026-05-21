"""
OzonCategory 域 - 领域服务（纯业务逻辑，无 I/O 依赖）。
"""
import json
import logging
import re
import requests
import time
from typing import Callable

logger = logging.getLogger(__name__)

LLMCallFunc = Callable[[str, str, float, int], tuple[dict | None, str]]


class TranslationService:
    """品类名称翻译领域服务（纯逻辑，通过注入的 LLM caller 执行 I/O）"""

    BATCH_SIZE = 20  # 每批翻译数量

    @staticmethod
    def build_translation_prompt(categories: list[dict]) -> str:
        """构建翻译 prompt（俄语品类名 → 中文）"""
        cat_lines = "\n".join([
            f"{j+1}. [{c['id']}] {c['path']}"
            for j, c in enumerate(categories)
        ])
        return f"""你是一个电商翻译助手。请将以下 Ozon 电商平台的俄语品类名称翻译成中文。

每个品类包含路径信息（"俄语>俄语"格式），你只需要翻译品类名本身。

翻译要求：
- 准确传达原意
- 使用电商行业通用术语
- 对于品牌词、专有名词保留原文

请严格按照以下 JSON 格式返回翻译结果，不要包含其他内容：
{{"translations": [
  {{"id": 123, "name_cn": "中文翻译"}},
  ...
]}}

需要翻译的品类列表：
{cat_lines}"""

    @staticmethod
    def parse_translation_response(llm_text: str) -> dict[str, str]:
        """解析 LLM 翻译响应，返回 {category_id_str: chinese_name}"""
        cleaned = llm_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("翻译 JSON 解析失败")
            return {}
        result = {}
        for t in parsed.get("translations", []):
            tid = str(t.get("id"))
            name_cn = t.get("name_cn", "")
            if tid and name_cn:
                result[tid] = name_cn
        return result

    @classmethod
    def batch_translate(
        cls,
        categories: list[dict],
        llm_call: LLMCallFunc,
        batch_label: str = "翻译",
    ) -> tuple[dict[str, str], int, int]:
        """
        批量翻译品类名。
        返回: (translations_dict, translated_count, error_count)
        """
        if not categories:
            return {}, 0, 0

        prompt = cls.build_translation_prompt(categories)
        system_prompt = "你是俄语→中文电商品类翻译专家。只返回 JSON，不要其他内容。"

        try:
            result, err = llm_call(system_prompt, prompt, 0.1, 32768)
            if err:
                logger.warning("[%s] LLM 调用失败: %s", batch_label, err)
                return {}, 0, len(categories)
            translations = cls.parse_translation_response(
                result.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            translated_count = len(translations)
            return translations, translated_count, len(categories) - translated_count
        except Exception as e:
            logger.error("[%s] 翻译异常: %s", batch_label, e)
            return {}, 0, len(categories)


class CategoryMatchingService:
    """品类匹配领域服务 — 逐层 LLM 选择"""

    @staticmethod
    def build_level_prompt(
        candidates: list[dict],
        product_title: str,
        product_category: str,
        product_description: str,
        level_desc: str,
    ) -> str:
        """构建当前层候选的 LLM prompt"""
        cand_lines = []
        for c in candidates:
            display = c["name"]
            if c.get("cn") and c["cn"] != c["name"]:
                display = f"{c['name']}（{c['cn']}）"
            leaf_mark = "" if c["is_leaf"] else " [含子品类]"
            cand_lines.append(f"[{c['id']}] {display}{leaf_mark}")

        return f"""## 产品信息
标题: {product_title or "未提供"}
品类: {product_category or "未提供"}
描述: {product_description[:300] if product_description else "未提供"}

## {level_desc}（共 {len(candidates)} 个）
{chr(10).join(cand_lines)}

请选择最匹配的一个品类。必须返回严格 JSON：
{{"category_id": <候选列表中的ID或null>, "reason": "<简短理由>"}}
如果都不合适，返回 {{"category_id": null, "reason": "<原因>"}}。
"""

    @staticmethod
    def parse_match_response(llm_text: str, valid_ids: set[str]) -> tuple[int | None, str]:
        """解析 LLM 匹配响应，返回 (category_id|None, error_message)"""
        cleaned = llm_text.strip()
        fence = chr(96) * 3
        if cleaned.startswith(fence):
            cleaned = re.sub(r"^" + fence + r"(?:json)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?" + fence + r"$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None, "JSON 解析失败"
        if not isinstance(parsed, dict):
            return None, "顶层不是 JSON object"
        if "category_id" not in parsed:
            return None, "缺少 category_id 字段"
        chosen_id = parsed.get("category_id")
        if chosen_id is None:
            return None, ""  # LLM 认为无合适品类
        if str(chosen_id) not in valid_ids:
            return None, f"category_id {chosen_id} 不在候选列表"
        return int(chosen_id), ""

    @staticmethod
    def keyword_score(candidate: dict, title_words: set[str]) -> int:
        """计算候选品类与标题关键词的匹配度"""
        name_lower = c["name"].lower()
        cn = c.get("cn", "").lower()
        score = 0
        for w in title_words:
            if len(w) > 1 and w in name_lower:
                score += 2
            if len(w) > 1 and w in cn:
                score += 1
        return score

    @staticmethod
    def build_path_str(path_nodes: list[dict], translations: dict[str, str]) -> str:
        """构建品类层级路径字符串（含中文翻译）"""
        parts = []
        for p in path_nodes:
            cn = translations.get(str(p["id"]), "")
            cn_leaf = cn.split(" > ")[-1] if cn else ""
            if cn_leaf and cn_leaf != p["name"]:
                parts.append(f"{p['name']}（{cn_leaf}）")
            else:
                parts.append(p["name"])
        return " > ".join(parts)

    @staticmethod
    def build_node_path(names_ids: list[tuple[str, str]], translations: dict[str, str]) -> tuple[list[str], list[str]]:
        """构建 node_path_names 和 node_path_ids"""
        names = []
        ids = []
        for nid, nru in names_ids:
            cn = translations.get(str(nid), "")
            cn_leaf = cn.split(" > ")[-1] if cn else ""
            if cn_leaf and cn_leaf != nru:
                names.append(f"{nru}（{cn_leaf}）")
            else:
                names.append(nru)
            ids.append(str(nid))
        return names, ids
