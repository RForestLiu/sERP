"""
OzonCategory 域 - 应用服务（用例编排）。
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Callable

import requests

from src.serp.shared import Result, DomainError

from ..domain.entities import CategoryTree, CategoryNode
from ..domain.value_objects import LLMConfig
from ..domain.services import TranslationService, CategoryMatchingService
from ..domain.events import CategoryTreeFetched, CategoriesTranslated, CategoriesRefreshed
from ..domain.repositories import (
    CategoryTreeCacheRepository,
    TranslationCacheRepository,
    AttributeTranslationCacheRepository,
    ExcludedCategoriesRepository,
)
from ..facade import OzonCategoryFacade

logger = logging.getLogger(__name__)


class OzonCategoryApplicationService(OzonCategoryFacade):
    """OzonCategory 域应用服务 — 实现 OzonCategoryFacade"""

    def __init__(
        self,
        tree_cache_repo: CategoryTreeCacheRepository,
        trans_cache_repo: TranslationCacheRepository,
        attr_trans_cache_repo: AttributeTranslationCacheRepository,
        excluded_repo: ExcludedCategoriesRepository,
        ozon_api: "OzonApiClient",
        llm_client: "DeepSeekLLMClient",
    ):
        self._tree_cache_repo = tree_cache_repo
        self._trans_cache_repo = trans_cache_repo
        self._attr_trans_cache_repo = attr_trans_cache_repo
        self._excluded_repo = excluded_repo
        self._ozon_api = ozon_api
        self._llm_client = llm_client
        self._refresh_tasks: dict[str, dict] = {}
        self._translations_lock = threading.Lock()
        self._attribute_values_cache: dict[tuple[str, int, int, int], list[dict]] = {}
        self._attribute_values_lock = threading.Lock()
        self._attribute_value_translations_lock = threading.Lock()

    # ==================== 查询 ====================

    def get_category_tree(self, store_id: str) -> dict:
        """获取品类树（含缓存）"""
        tree = self._load_or_fetch_tree(store_id)
        excluded = sorted(list(self._excluded_repo.load(store_id)))
        translations = self._trans_cache_repo.load(store_id)
        tree_data = tree.enrich_translations(translations) if translations else tree.to_dict()
        return {
            "success": True,
            "category_tree": tree_data,
            "excluded_ids": excluded,
            "node_count": tree.count_nodes(),
        }

    def get_refresh_status(self, store_id: str) -> dict:
        """查询刷新进度"""
        task = self._refresh_tasks.get(store_id)
        if not task:
            return {
                "exists": False,
                "status": "idle",
                "progress": 0,
                "message": "尚未执行过品类树刷新",
            }
        return {
            "exists": True,
            "status": task.get("status", "idle"),
            "progress": task.get("progress", 0),
            "message": task.get("message", ""),
            "total_groups": task.get("total_groups", 0),
            "current_group": task.get("current_group", 0),
            "total_nodes": task.get("total_nodes", 0),
            "translated": task.get("translated", 0),
            "need_translate": task.get("need_translate", 0),
            "error": task.get("error"),
            "has_result": task.get("status") == "completed",
        }

    # ==================== 命令 ====================

    def translate_categories(self, store_id: str, category_ids: list[int]) -> dict:
        """批量翻译品类名（俄→中）。从品类树查找节点名进行翻译。"""
        tree = self._load_or_fetch_tree(store_id)
        translations = self._trans_cache_repo.load(store_id)

        # 从树中查找对应 ID 的节点
        categories = []
        for cid in category_ids:
            node = tree.find_node(cid)
            if node is None:
                continue
            cat_name = node.name or node.type_name
            if str(cid) in translations:
                continue
            # 找到父级路径
            all_nodes = tree.flatten_all()
            for n in all_nodes:
                if str(n["id"]) == str(cid):
                    categories.append(n)
                    break

        if not categories:
            return {
                "success": True,
                "translations": [],
                "translated_count": len(translations),
                "total_categories": len(category_ids),
            }

        # 批处理翻译
        new_trans = {}
        trans_count = 0
        err_count = 0
        for i in range(0, len(categories), TranslationService.BATCH_SIZE):
            batch = categories[i:i + TranslationService.BATCH_SIZE]
            batch_trans, tc, ec = TranslationService.batch_translate(
                batch,
                self._llm_client.call,
                batch_label=f"品类翻译 batch {i // TranslationService.BATCH_SIZE + 1}",
            )
            new_trans.update(batch_trans)
            trans_count += tc
            err_count += ec

        # 保存增量到缓存
        if new_trans:
            self._trans_cache_repo.update(store_id, new_trans)

        translations = self._trans_cache_repo.load(store_id)
        result = []
        for cid in category_ids:
            name_cn = translations.get(str(cid), "")
            result.append({
                "id": cid,
                "name_cn": name_cn,
            })

        return {
            "success": True,
            "translations": result,
            "translated_count": len([r for r in result if r["name_cn"]]),
            "total_categories": len(category_ids),
        }

    def refresh_categories(self, store_id: str) -> dict:
        """刷新品类树（后台异步）"""
        if store_id in self._refresh_tasks and self._refresh_tasks[store_id].get("status") == "running":
            return {
                "success": True,
                "async": True,
                "message": "品类树正在刷新中，请稍候...",
            }

        thread = threading.Thread(
            target=self._run_refresh_background, args=(store_id,), daemon=True
        )
        thread.start()

        return {
            "success": True,
            "async": True,
            "message": "品类树刷新任务已启动",
        }

    @staticmethod
    def _candidate_from_node(node, translations: dict[str, str], parent_description_category_id: int | None = None) -> dict:
        nid = int(node.id) if node.id else 0
        description_category_id = (
            getattr(node, "description_category_id", 0)
            or parent_description_category_id
            or (0 if node.type_id else nid)
        )
        type_id = node.type_id or None
        return {
            "id": nid,
            "name": node.name or node.type_name,
            "cn": translations.get(str(nid), ""),
            "is_leaf": node.is_leaf,
            "node": node,
            "description_category_id": int(description_category_id or 0),
            "type_id": int(type_id) if type_id else None,
            "validation_id": int(description_category_id or nid),
        }

    def match_category(self, store_id: str, product_info: dict) -> dict:
        """AI 匹配最合适的品类"""
        product_title = product_info.get("product_title", "")
        product_category = product_info.get("product_category", "")
        product_description = product_info.get("product_description", "")

        if not product_title and not product_category:
            return {"error": "请提供产品标题或品类名称"}

        t_start = time.time()

        tree = self._load_or_fetch_tree(store_id)
        translations = self._trans_cache_repo.load(store_id)
        excluded_ids = set()

        logger.info("[品类匹配] store=%s, 标题=%s", store_id, product_title[:80])

        best_match = None
        trace = []
        frame_stack = [{
            "nodes": tree.root_nodes,
            "parent_path": [],
            "tried_ids": set(),
            "entry_id": None,
            "llm_fails": 0,
        }]

        title_lower = (product_title + " " + product_category).lower()
        title_words = set(title_lower.split())

        while frame_stack:
            frame = frame_stack[-1]
            candidates = []

            for node in frame["nodes"]:
                parent_description_category_id = None
                if frame.get("parent_path"):
                    parent_description_category_id = frame["parent_path"][-1].get("description_category_id")
                candidate = self._candidate_from_node(node, translations, parent_description_category_id)
                nid = candidate["id"]
                if candidate["is_leaf"] and candidate["description_category_id"] and int(candidate["description_category_id"]) in excluded_ids:
                    continue
                if nid in frame["tried_ids"]:
                    continue
                candidate["validation_id"] = frame.get("entry_id") or candidate["description_category_id"] or candidate["id"]
                candidates.append(candidate)

            if not candidates:
                self._mark_branch_exhausted(frame_stack)
                frame_stack.pop()
                continue

            depth = len(frame_stack) - 1
            path_desc = " > ".join(p["name"] for p in frame["parent_path"]) if frame["parent_path"] else "根级品类"
            all_leaves = all(c["is_leaf"] for c in candidates)

            # 叶子层候选少时用批量关键词验证
            if False and all_leaves and len(candidates) <= 20:
                logger.info("[品类匹配] 叶子层 %s 个候选，批量验证", len(candidates))
                first_c = candidates[0]
                group_vid = int(first_c.get("description_category_id") or first_c.get("validation_id") or first_c["id"])
                payload = {"description_category_id": group_vid}
                if first_c.get("type_id"):
                    payload["type_id"] = int(first_c["type_id"])
                result, err = self._ozon_api.call(
                    store_id, "/v1/description-category/attribute", payload
                )
                if err:
                    logger.warning("[品类匹配] 验证失败，排除=%s", group_vid)
                    self._excluded_repo.add(store_id, int(group_vid))
                    excluded_ids.add(int(group_vid))
                    for c in candidates:
                        frame["tried_ids"].add(int(c["id"]))
                    self._mark_branch_exhausted(frame_stack)
                    frame_stack.pop()
                    continue

                sorted_candidates = sorted(
                    candidates,
                    key=lambda c: CategoryMatchingService.keyword_score(c, title_words),
                    reverse=True,
                )
                found = False
                for c in sorted_candidates:
                    frame["parent_path"].append({
                        "id": c["id"], "name": c["name"], "node": c["node"],
                        "description_category_id": c.get("description_category_id"),
                    })
                    path_nodes = frame["parent_path"]
                    path_str = CategoryMatchingService.build_path_str(
                        path_nodes, translations
                    )
                    node_path_names, node_path_ids = self._build_node_path_entries(
                        path_nodes, translations
                    )
                    best_match = {
                        "id": c.get("description_category_id") or c.get("validation_id") or c["id"],
                        "type_id": c.get("type_id"),
                        "name": c["name"],
                        "path": path_str,
                        "node_path_names": node_path_names,
                        "node_path_ids": node_path_ids,
                        "reason": f"逐层匹配（共 {depth + 1} 层）→ {c['name']}（关键词验证）",
                    }
                    found = True
                    break

                if found:
                    break
                self._mark_branch_exhausted(frame_stack)
                frame_stack.pop()
                continue

            # LLM 选择
            logger.info("[品类匹配] 第 %s 层: %s 个候选 (LLM)", depth, len(candidates))
            chosen_id = None
            for attempt in range(2):
                allow_no_match = depth > 0 or all_leaves
                prompt = CategoryMatchingService.build_level_prompt(
                    candidates, product_title, product_category, product_description,
                    f"可选品类（当前层级：{path_desc}）",
                    allow_null=allow_no_match,
                )
                match_tool = CategoryMatchingService.build_category_match_tool(candidates, allow_no_match)
                llm_response, llm_err = self._llm_client.call(
                    "你是 Ozon 电商品类匹配专家。必须只返回 JSON 对象，字段为 category_id 和 reason；category_id 必须是候选列表里的 ID 或 null。",
                    prompt,
                    0.1,
                    256,
                    tools=[match_tool],
                    tool_choice={"type": "function", "function": {"name": "select_ozon_category"}},
                    thinking={"type": "disabled"},
                )
                if llm_err or not llm_response:
                    trace.append({
                        "depth": depth,
                        "path": path_desc,
                        "candidate_count": len(candidates),
                        "candidate_ids": [c["id"] for c in candidates[:20]],
                        "llm_error": llm_err or "empty_response",
                    })
                    frame["llm_fails"] += 1
                    continue
                llm_text = CategoryMatchingService.extract_match_response_text(llm_response)
                valid_ids = {str(c["id"]) for c in candidates}
                cid, parse_err = CategoryMatchingService.parse_match_response(
                    llm_text, valid_ids
                )
                trace.append({
                    "depth": depth,
                    "path": path_desc,
                    "candidate_count": len(candidates),
                    "candidate_ids": [c["id"] for c in candidates[:20]],
                    "llm_text": llm_text[:500],
                    "parse_error": parse_err,
                })
                if parse_err:
                    logger.warning("[品类匹配] 解析失败: %s", parse_err)
                    frame["llm_fails"] += 1
                    continue
                if cid is None:
                    frame["llm_fails"] += 1
                    continue
                chosen_id = cid
                break

            if chosen_id is None:
                if frame["llm_fails"] < 2:
                    continue
                self._mark_branch_exhausted(frame_stack)
                frame_stack.pop()
                continue

            chosen = next((c for c in candidates if int(c["id"]) == int(chosen_id)), None)
            if not chosen:
                frame["llm_fails"] += 1
                if frame["llm_fails"] < 2:
                    continue
                self._mark_branch_exhausted(frame_stack)
                frame_stack.pop()
                continue

            if chosen["is_leaf"]:
                vid = int(chosen.get("description_category_id") or chosen.get("validation_id") or chosen["id"])
                payload = {"description_category_id": vid}
                if chosen.get("type_id"):
                    payload["type_id"] = int(chosen["type_id"])
                logger.info("[品类匹配] 验证叶子: %s (ID=%s)", chosen["name"], chosen["id"])
                result, err = self._ozon_api.call(
                    store_id, "/v1/description-category/attribute", payload
                )
                if err:
                    self._excluded_repo.add(store_id, int(vid))
                    excluded_ids.add(int(vid))
                    frame["tried_ids"].add(int(chosen["id"]))
                    continue

                frame["parent_path"].append({
                    "id": chosen["id"], "name": chosen["name"], "node": chosen["node"],
                    "description_category_id": chosen.get("description_category_id"),
                })
                path_nodes = frame["parent_path"]
                path_str = CategoryMatchingService.build_path_str(
                    path_nodes, translations
                )
                node_path_names, node_path_ids = self._build_node_path_entries(
                    path_nodes, translations
                )
                best_match = {
                    "id": chosen.get("description_category_id") or chosen.get("validation_id") or chosen["id"],
                    "type_id": chosen.get("type_id"),
                    "name": chosen["name"],
                    "path": path_str,
                    "node_path_names": node_path_names,
                    "node_path_ids": node_path_ids,
                    "reason": f"逐层匹配（共 {depth + 1} 层）→ {chosen['name']}",
                }
                logger.info("[品类匹配] 验证通过: %s (ID=%s)", chosen["name"], chosen["id"])
                break
            else:
                frame["parent_path"].append({
                    "id": chosen["id"], "name": chosen["name"], "node": chosen["node"],
                    "description_category_id": chosen.get("description_category_id"),
                })
                children = chosen["node"].children
                frame_stack.append({
                    "nodes": children,
                    "parent_path": list(frame["parent_path"]),
                    "tried_ids": set(),
                    "entry_id": chosen.get("description_category_id") or chosen["id"],
                    "llm_fails": 0,
                })

        elapsed = time.time() - t_start
        return {
            "success": True,
            "best_match": best_match,
            "elapsed": round(elapsed, 1),
            "warning": "" if best_match else "LLM 未返回可用匹配结果",
            "trace": trace[-8:],
        }

    def get_category_attributes(self, store_id: str, category_id: int, type_id: int | None = None) -> dict:
        """获取品类属性及字典值"""
        logger.info("[品类属性] store=%s, category_id=%s", store_id, category_id)
        if not category_id:
            return {"error": "请提供 description_category_id"}

        payload = {"description_category_id": category_id}
        if type_id:
            payload["type_id"] = type_id
        result, err = self._ozon_api.call(
            store_id, "/v1/description-category/attribute", payload
        )

        if err:
            suggestions = []
            is_400 = "Error 400" in str(err) or "Error 404" in str(err) or "not found" in str(err).lower()
            if is_400:
                self._excluded_repo.add(store_id, category_id)
                tree = self._load_or_fetch_tree(store_id)
                parent = tree.find_parent(category_id)
                if parent:
                    for sibling in parent.children:
                        sid = int(sibling.id)
                        if sid != category_id and sibling.is_leaf:
                            suggestions.append({
                                "id": sid,
                                "name": sibling.name or sibling.type_name,
                            })
                else:
                    # 根级 — 取叶子兄弟
                    leaves = tree.collect_leaves()
                    for leaf in leaves[:20]:
                        lid = int(leaf.id)
                        if lid != category_id:
                            suggestions.append({
                                "id": lid,
                                "name": leaf.name or leaf.type_name,
                            })

                if suggestions:
                    suggestions = suggestions[:20]

                return {
                    "success": True,
                    "description_category_id": category_id,
                    "attributes": [],
                    "is_leaf": False,
                    "warning": f"当前品类（ID: {category_id}）没有可用属性，请选择其他品类。",
                    "suggestions": suggestions,
                }
            return {"error": str(err)}

        attributes_raw = result.get("result", [])
        logger.info("[品类属性] API 返回 %s 个属性", len(attributes_raw))

        enriched = []
        for attr in attributes_raw:
            eattr = {
                "id": attr.get("id"),
                "name": attr.get("name", ""),
                "description": attr.get("description", ""),
                "type": attr.get("type", ""),
                "dictionary_id": attr.get("dictionary_id", 0),
                "is_required": attr.get("is_required", False),
                "is_collection": attr.get("is_collection", False),
                "max_value_count": attr.get("max_value_count", 1),
                "dictionary_values": [],
            }

            enriched.append(eattr)

        value_attrs = [a for a in enriched if a["type"] == "dictionary" or a["dictionary_id"]]
        if value_attrs:
            def _load_for_attr(eattr: dict) -> tuple[int, list[dict]]:
                values_payload = {
                    "attribute_id": eattr["id"],
                    "description_category_id": category_id,
                    "limit": 100,
                }
                if type_id:
                    values_payload["type_id"] = type_id
                return eattr["id"], self._load_attribute_values(store_id, values_payload)

            with ThreadPoolExecutor(max_workers=min(6, len(value_attrs))) as executor:
                futures = [executor.submit(_load_for_attr, a) for a in value_attrs]
                values_by_attr = {}
                for future in as_completed(futures):
                    attr_id, values = future.result()
                    values_by_attr[attr_id] = values
                for eattr in value_attrs:
                    eattr["dictionary_values"] = values_by_attr.get(eattr["id"], [])

        # 翻译属性名
        if enriched:
            attr_names = [a["name"] for a in enriched if a["name"]]
            name_trans = self._translate_attr_names(store_id, attr_names)
            for a in enriched:
                a["name_cn"] = name_trans.get(a["name"], "")

        # 翻译属性描述
        if enriched:
            descs = [a["description"] for a in enriched if a["description"]]
            if descs:
                desc_trans = self._translate_attr_descs(store_id, descs)
                for a in enriched:
                    if a.get("description"):
                        a["description_cn"] = desc_trans.get(a["description"], "")

        is_leaf = len(enriched) > 0
        return {
            "success": True,
            "description_category_id": category_id,
            "type_id": type_id,
            "attributes": enriched,
            "is_leaf": is_leaf,
            "warning": "" if is_leaf else f"当前品类（ID: {category_id}）没有可配置的产品属性，请尝试选择一个更具体的子品类。",
        }

    def _load_attribute_values(self, store_id: str, values_payload: dict) -> list[dict]:
        cache_key = (
            store_id,
            int(values_payload.get("description_category_id") or 0),
            int(values_payload.get("type_id") or 0),
            int(values_payload.get("attribute_id") or 0),
        )
        with self._attribute_values_lock:
            cached = self._attribute_values_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        values: list[dict] = []
        payload = dict(values_payload)
        last_value_id = 0
        for _ in range(10):
            if last_value_id:
                payload["last_value_id"] = last_value_id
            vals_result, vals_err = self._ozon_api.call(
                store_id, "/v1/description-category/attribute/values", payload
            )
            if vals_err or not vals_result:
                break
            batch = vals_result.get("result", []) or []
            values.extend(self._attach_value_translations(store_id, batch))
            if not vals_result.get("has_next") or not batch:
                break
            last_value_id = batch[-1].get("id") or 0
            if not last_value_id:
                break
        with self._attribute_values_lock:
            self._attribute_values_cache[cache_key] = list(values)
        return values

    def _attach_value_translations(self, store_id: str, values: list[dict]) -> list[dict]:
        cached = self._attr_trans_cache_repo.load_values(store_id)
        changed = False
        enriched: list[dict] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            value_text = str(item.get("value") or item.get("name") or item.get("info") or "").strip()
            if not value_text:
                enriched.append(dict(item))
                continue
            value_cn = cached.get(value_text)
            if value_cn is None:
                value_cn = self._known_attribute_value_cn(value_text)
                if value_cn:
                    cached[value_text] = value_cn
                    changed = True
            next_item = dict(item)
            if value_cn:
                next_item["value_cn"] = value_cn
            enriched.append(next_item)

        if changed:
            with self._attribute_value_translations_lock:
                latest = self._attr_trans_cache_repo.load_values(store_id)
                latest.update({k: v for k, v in cached.items() if v})
                self._attr_trans_cache_repo.save_values(store_id, latest)
        return enriched

    @staticmethod
    def _known_attribute_value_cn(value: str) -> str:
        translations = {
            "Да": "是",
            "Нет": "否",
            "Китай": "中国",
            "Россия": "俄罗斯",
            "Китай (Тайвань)": "中国台湾",
            "Китай (Гонконг)": "中国香港",
            "Нейлон": "尼龙",
            "Металл": "金属",
            "Полиэстер": "聚酯纤维",
            "Пластик": "塑料",
            "ABS пластик": "ABS塑料",
            "Искусственная кожа": "人造革",
            "Натуральная кожа": "真皮",
            "Металлический сплав": "金属合金",
            "Металлизированный материал": "金属化材料",
            "Нетканое полотно": "无纺布",
            "Женский": "女",
            "Мужской": "男",
            "Унисекс": "男女通用",
            "черный": "黑色",
            "белый": "白色",
            "коричневый": "棕色",
            "бежевый": "米色",
            "розовый": "粉色",
            "синий": "蓝色",
            "красный": "红色",
            "серый": "灰色",
            "зеленый": "绿色",
            "желтый": "黄色",
            "фиолетовый": "紫色",
            "оранжевый": "橙色",
        }
        return translations.get(value.strip(), "")

    # ==================== 内部方法 ====================

    def _load_or_fetch_tree(self, store_id: str) -> CategoryTree:
        """加载品类树（缓存优先，缓存不存在则从 API 拉取并缓存）"""
        cached = self._tree_cache_repo.load(store_id)
        if cached is not None:
            return cached

        logger.info("[品类] 从 Ozon API 拉取品类树 | store=%s", store_id)
        result, err = self._ozon_api.call(store_id, "/v1/description-category/tree")
        if err:
            raise DomainError(f"获取品类树失败: {err}")

        tree_data = result.get("result", [])
        if not tree_data:
            raise DomainError("品类树为空")

        tree = CategoryTree.from_api_result(store_id, tree_data)
        self._tree_cache_repo.save(store_id, tree)
        logger.info("[品类] 品类树已缓存 | store=%s | 节点数=%s", store_id, tree.count_nodes())
        return tree

    def _run_refresh_background(self, store_id: str):
        """后台异步刷新品类树+翻译"""
        t_start = time.time()
        self._refresh_tasks[store_id] = {
            "status": "running",
            "progress": 0,
            "message": "拉取品类树...",
            "total_groups": 0,
            "current_group": 0,
            "total_nodes": 0,
            "translated": 0,
            "need_translate": 0,
            "error": None,
        }

        try:
            # 1. 强制重新拉取品类树
            self._refresh_tasks[store_id]["message"] = "正在从 Ozon API 拉取品类树..."
            result, err = self._ozon_api.call(store_id, "/v1/description-category/tree")
            if err:
                self._refresh_tasks[store_id]["status"] = "error"
                self._refresh_tasks[store_id]["error"] = f"获取品类树失败: {err}"
                return

            tree_data = result.get("result", [])
            if not tree_data:
                self._refresh_tasks[store_id]["status"] = "error"
                self._refresh_tasks[store_id]["error"] = "品类树为空"
                return

            tree = CategoryTree.from_api_result(store_id, tree_data)
            self._tree_cache_repo.save(store_id, tree)

            # 2. 展平所有节点
            self._refresh_tasks[store_id]["message"] = "展平品类树..."
            all_nodes = tree.flatten_all()
            total_count = len(all_nodes)
            self._refresh_tasks[store_id]["total_nodes"] = total_count

            # 3. 按 type_id 分组翻译
            translations = self._trans_cache_repo.load(store_id)
            untranslated = [n for n in all_nodes if str(n["id"]) not in translations]
            need_translate = len(untranslated)
            self._refresh_tasks[store_id]["need_translate"] = need_translate

            if need_translate > 0:
                groups = {}
                group_names = {}
                for n in untranslated:
                    tid = n.get("type_id", "unknown")
                    if tid not in groups:
                        groups[tid] = []
                        group_names[tid] = n.get("type_name", f"大类_{tid}")
                    groups[tid].append(n)

                type_ids_sorted = sorted(groups.keys(), key=lambda x: str(x))
                total_groups = len(type_ids_sorted)
                self._refresh_tasks[store_id]["total_groups"] = total_groups
                self._refresh_tasks[store_id]["message"] = f"开始翻译 0/{total_groups} 个大类..."

                trans_lock = threading.Lock()
                translated_count = 0

                def _translate_group(tid, batch, type_name, batch_index):
                    jitter = random.uniform(1.0, 2.0)
                    time.sleep(jitter)
                    batch_label = f"品类刷新 第{batch_index}/{total_groups}批({type_name})"
                    logger.info("[并发] 第 %s/%s 批 | %s (%s 个) | jitter=%.2fs",
                                batch_index, total_groups, type_name, len(batch), jitter)
                    trans_count, err_count = TranslationService.batch_translate(
                        batch, self._llm_client.call, batch_label=batch_label
                    )
                    # 批量翻译现在返回 (translations_dict, count, errors)
                    # 需要适配...
                    batch_trans, tc, ec = TranslationService.batch_translate(
                        batch, self._llm_client.call, batch_label=batch_label
                    )
                    with trans_lock:
                        nonlocal translated_count
                        for k, v in batch_trans.items():
                            translations[k] = v
                        translated_count += tc
                        self._trans_cache_repo.save(store_id, translations)
                    return tc, ec

                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {}
                    for bi, tid in enumerate(type_ids_sorted, 1):
                        batch = groups[tid]
                        type_name = group_names[tid]
                        f = executor.submit(_translate_group, tid, batch, type_name, bi)
                        futures[f] = bi

                    for f in as_completed(futures):
                        idx = futures[f]
                        try:
                            cnt, _ = f.result()
                            progress_pct = int(idx / total_groups * 100)
                            with trans_lock:
                                self._refresh_tasks[store_id].update({
                                    "current_group": idx,
                                    "progress": progress_pct,
                                    "translated": translated_count,
                                    "message": f"已翻译 {idx}/{total_groups} 个大类（{translated_count}/{need_translate} 个品类）",
                                })
                        except Exception as e:
                            logger.error("[并发] 批次 %s/%s 异常: %s", idx, total_groups, e)

            else:
                self._refresh_tasks[store_id]["message"] = "所有品类已有翻译缓存"

            elapsed = time.time() - t_start
            self._refresh_tasks[store_id].update({
                "status": "completed",
                "progress": 100,
                "message": f"品类树已更新，共 {total_count} 个品类",
            })

            logger.info("[品类刷新] 完成 | 总耗时 %.1fs", elapsed)

            # 后台预检（可选，简化处理）
            self._preflight_categories_background(store_id)

        except Exception as e:
            self._refresh_tasks[store_id].update({
                "status": "error",
                "error": str(e),
                "message": f"刷新失败: {str(e)}",
            })
            logger.error("[品类刷新] 异常: %s", e)

    def _preflight_categories_background(self, store_id: str):
        """后台增量预检叶子品类属性可用性"""
        def _run():
            logger.info("[预检] 开始 | store=%s", store_id)
            tree = self._tree_cache_repo.load(store_id)
            if tree is None:
                return
            excluded = self._excluded_repo.load(store_id)
            leaves = tree.collect_leaves()
            untested = [leaf for leaf in leaves if int(leaf.id) not in excluded]
            logger.info("[预检] 总叶子: %s, 待预检: %s", len(leaves), len(untested))
            batch_size = 10
            for i in range(0, len(untested), batch_size):
                batch = untested[i:i + batch_size]
                for leaf in batch:
                    try:
                        result, err = self._ozon_api.call(
                            store_id, "/v1/description-category/attribute",
                            {"description_category_id": int(leaf.id)}
                        )
                        if err:
                            self._excluded_repo.add(store_id, int(leaf.id))
                    except Exception:
                        pass
            logger.info("[预检] 完成 | store=%s", store_id)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _translate_attr_names(self, store_id: str, attr_names: list[str]) -> dict[str, str]:
        """批量翻译属性名"""
        cached = self._attr_trans_cache_repo.load_names(store_id)
        untranslated = [n for n in attr_names if n and n not in cached]
        if not untranslated:
            return cached

        logger.info("[属性翻译] 翻译 %s 个属性名", len(untranslated))
        prompt = f"""翻译以下俄语电商属性名为中文，返回 JSON 对象格式：{{"俄语名": "中文翻译"}}
只返回 JSON，不要其他内容。

{json.dumps(untranslated, ensure_ascii=False)}"""

        try:
            result, err = self._llm_client.call(
                "你是俄语→中文跨境电商翻译助手。只返回严格 JSON。",
                prompt, temperature=0.1, max_tokens=4096,
            )
            if not err and result:
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
                    cleaned = re.sub(r'\n?```$', '', cleaned)
                try:
                    new_trans = json.loads(cleaned)
                    if isinstance(new_trans, dict):
                        cached.update(new_trans)
                        self._attr_trans_cache_repo.save_names(store_id, cached)
                except json.JSONDecodeError:
                    logger.warning("[属性翻译] JSON 解析失败")
        except Exception as e:
            logger.warning("[属性翻译] 失败: %s", e)

        return cached

    def _translate_attr_descs(self, store_id: str, descriptions: list[str]) -> dict[str, str]:
        """批量翻译属性描述"""
        cached = self._attr_trans_cache_repo.load_descriptions(store_id)
        untranslated = [d for d in descriptions if d and d not in cached]
        if not untranslated:
            return cached

        logger.info("[描述翻译] 翻译 %s 个属性描述", len(untranslated))
        prompt = f"""翻译以下俄语电商属性描述为中文，返回 JSON 对象格式：{{"俄语描述": "中文翻译"}}
只返回 JSON，不要其他内容。

{json.dumps(untranslated, ensure_ascii=False)}"""

        try:
            result, err = self._llm_client.call(
                "你是俄语→中文跨境电商翻译助手。只返回严格 JSON。",
                prompt, temperature=0.1, max_tokens=4096,
            )
            if not err and result:
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
                    cleaned = re.sub(r'\n?```$', '', cleaned)
                try:
                    new_trans = json.loads(cleaned)
                    if isinstance(new_trans, dict):
                        cached.update(new_trans)
                        self._attr_trans_cache_repo.save_descriptions(store_id, cached)
                except json.JSONDecodeError:
                    logger.warning("[描述翻译] JSON 解析失败")
        except Exception as e:
            logger.warning("[描述翻译] 失败: %s", e)

        return cached

    @staticmethod
    def _mark_branch_exhausted(frame_stack):
        """当前帧子节点全部耗尽时，把入口 ID 标记到父帧"""
        if len(frame_stack) >= 2:
            entry = frame_stack[-1].get("entry_id")
            if entry:
                frame_stack[-2]["tried_ids"].add(int(entry))

    @staticmethod
    def _build_node_path_entries(path_nodes: list[dict], translations: dict[str, str]) -> tuple[list[str], list[str]]:
        """构建 node_path_names 和 node_path_ids 列表"""
        names = []
        ids = []
        for p in path_nodes:
            pn = p.get("node", p)
            n_ru = (pn.name or pn.get("type_name", "")) if hasattr(pn, 'name') else p.get("name", "")
            nid = str(p["id"])
            n_cn = translations.get(nid, "")
            n_cn_leaf = n_cn.split(" > ")[-1] if n_cn else ""
            if n_cn_leaf and n_cn_leaf != n_ru:
                names.append(f"{n_ru}（{n_cn_leaf}）")
            else:
                names.append(n_ru)
            ids.append(nid)
        return names, ids
