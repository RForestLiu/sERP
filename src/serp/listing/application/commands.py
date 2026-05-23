"""
Listing 域 - 应用服务（用例编排）。
"""
from __future__ import annotations

import json
import logging
import re
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING

from src.serp.shared import EventBus

from ..domain.entities import ListingDraft
from ..domain.services import (
    OzonQualityScorer,
    AttributePresetMatcher,
    DeterministicPreFiller,
)
from ..domain.ozon_workbench import (
    WALLET_CATEGORY_ID,
    WALLET_TYPE_ID,
    build_wallet_rich_content,
    collect_ozon_skus,
    resolve_wallet_brand,
    rich_content_to_attribute_value,
    validate_workbench_payload,
)
from ..domain.events import (
    ListingSimulated,
    ProductImportedToOzon,
    ProductsSynced,
)
from ..domain.repositories import ListingDraftRepository
from ..facade import ListingFacade
from .dto import (
    DraftViewDTO,
    ListingSimulateDTO,
    ProductCreateDTO,
    SyncResultDTO,
    AutoFillAnalyzeDTO,
    AutoFillOzonFieldsDTO,
)

if TYPE_CHECKING:
    from src.serp.settings.facade import SettingsFacade
    from src.serp.product.facade import ProductFacade
    from src.serp.ozon_category.facade import OzonCategoryFacade
    from ..infrastructure.ozon_api import OzonApiClient
    from ..infrastructure.autofill_client import DeepSeekAutoFillClient

logger = logging.getLogger(__name__)


class ListingApplicationService(ListingFacade):
    """Listing 域应用服务 — 实现 ListingFacade"""

    def __init__(
        self,
        draft_repo: ListingDraftRepository,
        ozon_api: "OzonApiClient",
        autofill_client: "DeepSeekAutoFillClient",
        settings_facade: "SettingsFacade",
        product_facade: "ProductFacade",
        ozon_category_facade: "OzonCategoryFacade",
        event_bus: EventBus,
        data_root: str,
    ):
        self._draft_repo = draft_repo
        self._ozon_api = ozon_api
        self._autofill_client = autofill_client
        self._settings_facade = settings_facade
        self._product_facade = product_facade
        self._ozon_category_facade = ozon_category_facade
        self._event_bus = event_bus
        self._data_root = data_root
        self._sync_state_file = os.path.join(data_root, "sync_state.json")

    # ==================== 草稿管理 ====================

    def get_draft(self, skc: str, store_id: str) -> dict:
        draft = self._draft_repo.find_by_skc_store(skc, store_id)
        if draft is None:
            return {"exists": False, "listing": None}
        return {"exists": True, "listing": draft.to_dict()}

    def save_draft(self, skc: str, store_id: str, data: dict) -> dict:
        existing = self._draft_repo.find_by_skc_store(skc, store_id)
        if existing is None:
            existing = ListingDraft(skc=skc, store_id=store_id)
        existing.update(data)
        self._draft_repo.save(existing)
        for event in existing.collect_events():
            self._event_bus.publish(event)
        return {"success": True, "updated_at": existing.updated_at}

    def delete_draft(self, skc: str, store_id: str):
        existing = self._draft_repo.find_by_skc_store(skc, store_id)
        if existing is not None:
            existing.mark_deleted()
            self._draft_repo.delete_by_skc_store(skc, store_id)
            for event in existing.collect_events():
                self._event_bus.publish(event)
        return {"success": True}

    # ==================== Ozon 上架 API ====================

    def simulate(self, store_id: str, data: dict) -> dict:
        skc = data.get("skc", "")
        report = OzonQualityScorer.score(data)
        self._append_lifecycle(skc, store_id, {
            "event": "simulate",
            "score": report["score"],
            "can_submit": report["can_submit"],
            "issues": report["issues"],
            "warnings": report["warnings"][:5],
        })
        self._event_bus.publish(ListingSimulated(
            skc=skc, store_id=store_id,
            score=report["score"], can_submit=report["can_submit"],
        ))
        return {"success": True, "store_id": store_id, "skc": skc, "report": report}

    def create_product(self, store_id: str, data: dict) -> dict:
        skc = data.get("skc", "")
        name = data.get("name", "")
        description = data.get("description", "")
        price = data.get("price", "")
        offer_id = data.get("offer_id", "")
        barcode = data.get("barcode", "")
        category_id = data.get("category_id", 0)
        type_id = data.get("type_id")
        attrs = data.get("attributes", [])
        images = data.get("images", [])
        videos = data.get("videos", [])
        skus = data.get("skus", []) or self._default_skus_from_product(skc, price)
        quality_report = OzonQualityScorer.score(data)

        if not quality_report["can_submit"]:
            self._append_lifecycle(skc, store_id, {
                "event": "quality_gate_failed",
                "score": quality_report["score"],
                "issues": quality_report["issues"],
                "warnings": quality_report["warnings"][:5],
            })
            return {
                "success": False,
                "error": f"Ozon 模拟上架评分 {quality_report['score']}，未达到 80 分或存在阻断问题",
                "quality_report": quality_report,
            }

        if not name or not price:
            return {"success": False, "error": "产品名称、价格为必填项"}

        if not category_id:
            return {"success": False, "error": "请先匹配产品品类"}

        # 格式化属性（过滤掉 Rich Content 11254，格式不合法）
        ozon_attrs = self._format_ozon_attributes(attrs)
        ozon_attrs = [a for a in ozon_attrs if a.get("id") != 11254]

        # 图片和视频
        from ..domain.services import _extract_public_image_urls
        base_image_urls = _extract_public_image_urls(images, 10)
        base_video_urls = [v.get("url", "") for v in videos if v.get("url", "").startswith("http")]

        # 从产品库提取重量和尺寸，填写 Ozon item 层字段
        weight, depth, width, height = self._extract_item_dimensions(skc)

        # 构建 items
        items = self._build_ozon_items(
            skus=skus, name=name, price=price, offer_id=offer_id,
            barcode=barcode, category_id=category_id, type_id=type_id,
            description=description, ozon_attrs=ozon_attrs,
            base_image_urls=base_image_urls, base_video_urls=base_video_urls,
            images=images,
            weight=weight, depth=depth, width=width, height=height,
        )

        if not items:
            return {"success": False, "error": "没有可提交的产品变种"}

        payload = {"items": items}
        result, err = self._ozon_api.call(store_id, "/v3/product/import", payload)

        if err:
            user_msg = err
            try:
                err_data = json.loads(err.replace("Ozon API Error 400: ", "").replace("Ozon API Error 500: ", ""))
                if isinstance(err_data, dict):
                    if "message" in err_data:
                        user_msg = err_data["message"]
                    elif "details" in err_data:
                        details = err_data["details"]
                        if isinstance(details, list) and details:
                            user_msg = "; ".join(str(d.get("message", d)) for d in details[:3])
            except Exception:
                pass
            self._append_lifecycle(skc, store_id, {
                "event": "ozon_import_failed",
                "score": quality_report["score"],
                "error": user_msg,
            })
            return {"success": False, "error": f"Ozon 上架失败: {user_msg}", "quality_report": quality_report}

        task_id = result.get("result", {}).get("task_id", "")
        self._append_lifecycle(skc, store_id, {
            "event": "ozon_import_submitted",
            "mode": "upsert",
            "score": quality_report["score"],
            "task_id": task_id,
            "item_count": len(items),
        })
        self._event_bus.publish(ProductImportedToOzon(
            skc=skc, store_id=store_id, task_id=task_id,
            item_count=len(items), score=quality_report["score"],
        ))

        return {
            "success": True,
            "task_id": task_id,
            "skc": skc,
            "item_count": len(items),
            "quality_report": quality_report,
            "message": f"已提交 {len(items)} 个产品变种到 Ozon（任务ID: {task_id}），请稍后在 Ozon 后台查看上架状态。",
        }

    def sync_products(self, store_id: str, data: dict) -> dict:
        logger.info("[产品同步] 开始同步 store_id=%s", store_id)

        # Step 1: 分页获取全量 offer_id
        all_offer_ids: list[str] = []
        last_id = ""
        page = 0
        while True:
            page += 1
            payload = {"limit": 100, "filter": {"visibility": "ALL"}}
            if last_id:
                payload["last_id"] = last_id
            result, err = self._ozon_api.call(store_id, "/v3/product/list", payload)
            if err:
                logger.error("[产品同步] 获取产品列表失败: %s", err)
                return {"success": False, "error": f"获取 Ozon 产品列表失败: {err}"}
            items = (result or {}).get("result", {}).get("items", [])
            total = (result or {}).get("result", {}).get("total", 0)
            for item in items:
                oid = item.get("offer_id", "")
                if oid:
                    all_offer_ids.append(oid)
            logger.info("[产品同步] 第%s页: %s 个 | 累计: %s/%s", page, len(items), len(all_offer_ids), total)
            last_id = (result or {}).get("result", {}).get("last_id", "")
            if not last_id or len(items) == 0:
                break

        # Step 2: 批量获取产品详情
        all_info_items: list[dict] = []
        for i in range(0, len(all_offer_ids), 100):
            batch = all_offer_ids[i:i + 100]
            result, err = self._ozon_api.call(store_id, "/v3/product/info/list", {"offer_id": batch})
            if err:
                logger.error("[产品同步] 获取产品详情失败: %s", err)
                return {"success": False, "error": f"获取产品详情失败: {err}"}
            all_info_items.extend((result or {}).get("items", []))

        logger.info("[产品同步] 获取 %s 个产品详情", len(all_info_items))

        # Step 3: 加载本地产品，建立 offer_id 索引
        products = self._product_facade.list_products()
        offer_index: dict[str, dict] = {}
        for pi, p in enumerate(products):
            for sku in (p.get("skus") or []):
                offer_index[sku] = {"skc": p.get("skc", ""), "idx": pi}

        # Step 4: 匹配 & 更新状态
        matched = 0
        new_skus = 0
        updated = 0
        synced: list[dict] = []

        for info in all_info_items:
            offer_id = info.get("offer_id", "")
            product_id = info.get("product_id") or info.get("id", 0)
            name_o = info.get("name", "")
            statuses = info.get("statuses", {})
            is_archived = info.get("is_archived") or info.get("is_autoarchived")

            if not offer_id:
                continue

            moderate = statuses.get("moderate_status", "")
            ozon_status = statuses.get("status", "")
            if is_archived:
                mapped_status = "已下架"
            elif moderate == "approved":
                mapped_status = "已上架"
            elif moderate == "declined":
                mapped_status = "审核拒绝"
            elif ozon_status == "new":
                mapped_status = "审核中"
            else:
                mapped_status = "已上架" if ozon_status == "price_sent" else ozon_status

            entry = offer_index.get(offer_id)
            if entry:
                skc = entry["skc"]
                p = products[entry["idx"]]
                if "store_status" not in p:
                    p["store_status"] = {}
                old_status = p["store_status"].get(store_id, "")
                p["store_status"][store_id] = mapped_status
                if old_status != mapped_status:
                    updated += 1
                    self._product_facade.update_store_status(skc, {"store_id": store_id, "status": mapped_status})
                matched += 1
                synced.append({
                    "skc": skc, "offer_id": offer_id, "product_id": product_id,
                    "name": name_o[:60], "status": mapped_status, "match": "matched",
                })
            else:
                new_skus += 1
                synced.append({
                    "skc": "", "offer_id": offer_id, "product_id": product_id,
                    "name": name_o[:60], "status": mapped_status, "match": "new",
                })

        # 更新同步状态
        self._save_sync_state(store_id, matched)
        now_iso = datetime.now().isoformat()

        logger.info("[产品同步] 完成 | 匹配=%s | 更新=%s | 新SKU=%s", matched, updated, new_skus)

        self._event_bus.publish(ProductsSynced(
            store_id=store_id, matched=matched, updated=updated, new_skus=new_skus,
        ))

        return {
            "success": True,
            "total_ozon_products": len(all_info_items),
            "matched": matched,
            "new_skus": new_skus,
            "updated": updated,
            "synced_products": synced,
            "last_sync": now_iso,
            "message": f"同步完成：{matched} 个匹配，{updated} 个状态更新，{new_skus} 个新SKU待注册",
        }

    # ── Ozon Workbench ──

    def auto_category(self, store_id: str, data: dict) -> dict:
        product = self._find_product_by_skc(data.get("skc", ""))
        product_info = dict(product or {})
        product_info.update(data)
        result = self._ozon_category_facade.match_category(store_id, {
            "product_title": product_info.get("product_title") or product_info.get("name") or product_info.get("title") or "",
            "product_category": product_info.get("product_category") or product_info.get("category") or "",
            "product_description": product_info.get("product_description") or product_info.get("description") or "",
        })
        if result.get("error"):
            return {"success": False, "store_id": store_id, "error": result["error"]}
        best_match = result.get("best_match") or {}
        if not best_match.get("id"):
            return {
                "success": False,
                "store_id": store_id,
                "error": result.get("warning") or "AI category match did not return a usable category",
                "raw": result,
            }
        return {"success": True, "store_id": store_id, "match": best_match, "raw": result}

    def generate_workbench_draft(self, store_id: str, data: dict) -> dict:
        skc = data.get("skc", "")
        product = self._find_product_by_skc(skc) or {}
        product_data = product.get("product_data", {}) or {}
        manual_data = product.get("manual_data", {}) or {}
        category_result = self.auto_category(store_id, {**product, **data})
        if not category_result.get("success"):
            return category_result
        category = category_result["match"]
        category_id = category.get("id")
        type_id = category.get("type_id")
        category_attrs_result = self._ozon_category_facade.get_category_attributes(store_id, int(category_id), int(type_id) if type_id else None)
        if category_attrs_result.get("error"):
            return {"success": False, "store_id": store_id, "error": category_attrs_result["error"]}
        ozon_attributes = category_attrs_result.get("attributes") or []
        image_urls = self._extract_input_image_urls(data.get("images", []))

        offer_id = data.get("offer_id") or (product.get("skus") or [skc])[0] if (product.get("skus") or [skc]) else skc
        title = data.get("name") or self._default_wallet_title(product, offer_id)
        description = data.get("description") or self._default_wallet_description(product)
        price = str(data.get("price") or product.get("price") or "99.00")

        attrs = self._default_wallet_attributes(
            offer_id=offer_id,
            title=title,
            description=description,
            product_data=product_data,
            manual_data=manual_data,
            image_urls=image_urls,
        )
        autofill_result = self.fill_ozon_fields({
            "skc": skc,
            "product_title": title,
            "product_data": product_data,
            "manual_data": manual_data,
            "ozon_attributes": ozon_attributes,
        })
        llm_attrs = self._normalize_autofill_attributes(autofill_result, ozon_attributes)
        attrs = self._merge_workbench_attributes(attrs, llm_attrs)
        skus = self._default_workbench_skus(product, offer_id, price, data.get("skus") or [])
        draft = {
            "skc": skc,
            "store_id": store_id,
            "name": title,
            "description": description,
            "price": price,
            "offer_id": offer_id,
            "category_id": category_id,
            "type_id": type_id,
            "category_match": category,
            "category_attributes_count": len(ozon_attributes),
            "attributes": attrs,
            "images": data.get("images") or [],
            "skus": skus,
            "llm_sessions": [{
                "name": "ozon_attribute_autofill",
                "success": not bool(autofill_result.get("error")),
                "error": autofill_result.get("error", ""),
                "filled_count": len(llm_attrs),
            }],
        }
        validation = validate_workbench_payload(draft)
        return {"success": True, "store_id": store_id, "draft": draft, "validation": validation}

    def validate_workbench_payload(self, store_id: str, data: dict) -> dict:
        report = validate_workbench_payload(data)
        return {"success": True, "store_id": store_id, "report": report}

    def prepare_images(self, store_id: str, data: dict) -> dict:
        base_url = str(data.get("base_url") or "").rstrip("/")
        prepared: list[dict] = []
        warnings: list[str] = []
        for img in data.get("images") or []:
            if not isinstance(img, dict):
                continue
            url = str(img.get("url") or "").strip()
            if url.startswith("/product_images/") and base_url:
                new_img = dict(img)
                new_img["url"] = base_url + url
                new_img["public_url_status"] = "prepared_from_local_static"
                prepared.append(new_img)
            elif url.startswith(("http://", "https://")):
                new_img = dict(img)
                new_img["public_url_status"] = "already_public"
                prepared.append(new_img)
            else:
                warnings.append(f"图片缺少公网 URL: {img.get('filename') or img.get('local_path') or url}")
        return {
            "success": True,
            "store_id": store_id,
            "images": prepared,
            "prepared_count": len(prepared),
            "warnings": warnings,
            "provider": "existing-url",
        }

    def upsert_workbench(self, store_id: str, data: dict) -> dict:
        report = validate_workbench_payload(data)
        if not report["can_submit"]:
            return {"success": False, "error": "Workbench 验证未通过", "validation": report}

        ozon_attrs = self._format_ozon_attributes(data.get("attributes", []))
        base_image_urls = self._extract_input_image_urls(data.get("images", []))
        base_video_urls = [v.get("url", "") for v in data.get("videos", []) if v.get("url", "").startswith("http")]
        weight, depth, width, height = self._extract_item_dimensions(data.get("skc", ""))
        items = self._build_ozon_items(
            skus=data.get("skus") or [],
            name=data.get("name", ""),
            price=data.get("price", ""),
            offer_id=data.get("offer_id", ""),
            barcode=data.get("barcode", ""),
            category_id=data.get("category_id"),
            type_id=data.get("type_id"),
            description=data.get("description", ""),
            ozon_attrs=ozon_attrs,
            base_image_urls=base_image_urls,
            base_video_urls=base_video_urls,
            images=data.get("images", []),
            weight=weight,
            depth=depth,
            width=width,
            height=height,
        )
        if not items:
            return {"success": False, "error": "没有可提交的商品变体", "validation": report}
        result, err = self._ozon_api.call(store_id, "/v3/product/import", {"items": items})
        if err:
            return {"success": False, "error": f"Ozon 上架失败: {err}", "validation": report}
        task_id = result.get("result", {}).get("task_id", "")
        self._append_lifecycle(data.get("skc", ""), store_id, {
            "event": "workbench_upsert_submitted",
            "task_id": task_id,
            "item_count": len(items),
            "score": report["score"],
        })
        return {"success": True, "task_id": task_id, "item_count": len(items), "validation": report}

    def official_rating(self, store_id: str, data: dict) -> dict:
        skus = collect_ozon_skus(data.get("skus") or [])
        offer_id = data.get("offer_id", "")
        if not skus and offer_id:
            product_info, err = self._ozon_api.call(store_id, "/v3/product/info/list", {"offer_id": [offer_id]})
            if err:
                return {"success": False, "error": f"Ozon product info failed: {err}"}
            skus = collect_ozon_skus(product_info)
        if not skus:
            return {"success": False, "error": "未能解析 Ozon 数字 SKU"}
        rating, err = self._ozon_api.call(store_id, "/v1/product/rating-by-sku", {"skus": skus})
        if err:
            return {"success": False, "error": f"Ozon content rating failed: {err}", "skus": skus}
        return {"success": True, "store_id": store_id, "skus": skus, "result": rating}

    # ── Ozon 导入状态查询 ──

    def check_import_status(self, store_id: str, task_id: str) -> dict:
        """查询 Ozon 导入任务状态，按 offer_id 分组返回 errors/warnings"""
        result, err = self._ozon_api.import_info(store_id, task_id)
        if err:
            return {"success": False, "error": f"查询 Ozon 导入状态失败: {err}"}

        raw_items = (result or {}).get("result", {}).get("items", [])
        grouped: dict[str, dict] = {}
        for item in raw_items:
            offer_id = item.get("offer_id", "")
            if not offer_id:
                continue
            errors = item.get("errors") or []
            translated_errors: list[dict] = []
            translated_warnings: list[dict] = []
            for e in errors:
                code = e.get("code", "")
                message = e.get("message", "")
                level = e.get("level", "error")  # error / warning
                cn_desc = self._translate_ozon_error(code, message)
                entry = {
                    "code": code,
                    "message": message,
                    "level": level,
                    "description_cn": cn_desc,
                }
                if level == "warning":
                    translated_warnings.append(entry)
                else:
                    translated_errors.append(entry)
            grouped[offer_id] = {
                "offer_id": offer_id,
                "product_id": item.get("product_id", 0),
                "status": item.get("status", ""),
                "errors": translated_errors,
                "warnings": translated_warnings,
                "error_count": len(translated_errors),
                "warning_count": len(translated_warnings),
            }

        total_errors = sum(g["error_count"] for g in grouped.values())
        total_warnings = sum(g["warning_count"] for g in grouped.values())
        all_imported = all(g["status"] == "imported" for g in grouped.values()) if grouped else False

        return {
            "success": True,
            "task_id": task_id,
            "store_id": store_id,
            "total_items": len(grouped),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "all_imported": all_imported,
            "items": list(grouped.values()),
            "summary": (
                f"共 {len(grouped)} 个商品: "
                + (f"全部导入成功" if all_imported and total_errors == 0
                   else f"{total_errors} 个阻断错误, {total_warnings} 个警告")
            ),
        }

    @staticmethod
    def _translate_ozon_error(code: str, message: str = "") -> str:
        """把 Ozon 错误码翻译成中文修复建议"""
        mapping = {
            "error_attribute_values_out_of_range": "属性值不在字典可选范围内，请使用 Ozon 字典值（dictionary_value_id）替代字符串",
            "invalid_rich_content_json": "Rich Content JSON 格式不符合 Ozon 模板规范，当前版本请移除该属性后再提交",
            "missing_dimension": "缺少商品重量或尺寸信息（weight/depth/width/height），请在 item 层补充",
            "error_attribute_value_not_found": "属性值在 Ozon 字典中未找到，请查询正确字典值后提交",
            "error_attribute_required": "缺少必填属性，请补全该属性后再提交",
            "error_offer_id_already_exists": "offer_id 已存在，将作为增量更新处理",
            "error_validation": f"字段校验失败: {message}" if message else "字段校验失败，请检查提交数据格式",
            "error_category_not_found": "类目 ID 无效或不存在",
            "error_price_invalid": "价格格式无效",
            "error_image_url_invalid": "图片 URL 无效或不可访问",
        }
        if code in mapping:
            return mapping[code]
        # 通用回退: 展示原始 code + message
        if message:
            return f"{code}: {message}"
        return f"未知错误 ({code})"

    # ==================== AI 填充 ====================

    def get_content_rating(self, store_id: str, skus: list[str]) -> dict:
        clean_skus = [str(s).strip() for s in skus if str(s).strip()]
        if not clean_skus:
            return {"success": False, "error": "missing skus"}

        result, err = self._ozon_api.content_rating_by_sku(store_id, clean_skus)
        if err:
            return {"success": False, "error": f"Ozon content rating failed: {err}"}
        return {"success": True, "store_id": store_id, "skus": clean_skus, "result": result}

    def analyze_for_autofill(self, data: dict) -> dict:
        skc = data.get("skc", "")
        product_title = data.get("product_title", "")
        product_data = data.get("product_data", {})
        manual_data = data.get("manual_data", {})
        form_fields = data.get("form_fields", [])
        custom_prompts = data.get("custom_prompts", {})
        variant_list = data.get("variant_list", [])
        variant_row_summary = data.get("variant_row_summary", {})

        if not form_fields:
            return {"error": "表单字段列表不能为空"}

        if not self._autofill_client.is_configured:
            return {"error": "DEEPSEEK_API_KEY not configured"}

        try:
            mappings = self._autofill_client.analyze_dianxiaomi(
                skc=skc,
                product_title=product_title,
                product_data=product_data,
                manual_data=manual_data,
                form_fields=form_fields,
                custom_prompts=custom_prompts,
                variant_list=variant_list,
                variant_row_summary=variant_row_summary,
            )
            return {
                "success": True,
                "skc": skc,
                "mappings": mappings,
                "total_fields": len(form_fields),
                "filled_fields": len(mappings),
            }
        except Exception as e:
            return {"error": str(e)}

    def fill_ozon_fields(self, data: dict) -> dict:
        skc = data.get("skc", "")
        product_title = data.get("product_title", "")
        product_data = data.get("product_data", {})
        manual_data = data.get("manual_data", {})
        ozon_attributes = data.get("ozon_attributes", [])

        if not ozon_attributes:
            return {"error": "Ozon 属性列表不能为空"}

        if not self._autofill_client.is_configured:
            return {"error": "DEEPSEEK_API_KEY not configured"}

        try:
            result = self._autofill_client.fill_ozon_attributes(
                skc=skc,
                product_title=product_title,
                product_data=product_data,
                manual_data=manual_data,
                ozon_attributes=ozon_attributes,
            )
            return result
        except Exception as e:
            return {"error": str(e)}

    # ==================== 内部辅助方法 ====================

    @staticmethod
    def _normalize_autofill_attributes(fill_result: dict, ozon_attributes: list[dict]) -> list[dict]:
        if fill_result.get("error"):
            return []

        raw_attrs = (
            fill_result.get("filled_attributes")
            or fill_result.get("attributes")
            or fill_result.get("results")
            or []
        )
        attr_index = {str(attr.get("id") or attr.get("attribute_id")): attr for attr in ozon_attributes}
        normalized: list[dict] = []
        for item in raw_attrs:
            if not isinstance(item, dict):
                continue
            attr_id = item.get("attribute_id") or item.get("id")
            try:
                attr_id = int(attr_id)
            except (TypeError, ValueError):
                continue
            attr_meta = attr_index.get(str(attr_id), {})
            value = item.get("value", "")
            if value is None:
                value = ""
            normalized_item = {
                "attribute_id": attr_id,
                "value": str(value),
                "type": item.get("type") or attr_meta.get("type") or "String",
                "source": item.get("source") or "llm_autofill",
            }
            dictionary_value_id = item.get("dictionary_value_id")
            if dictionary_value_id:
                normalized_item["dictionary_value_id"] = dictionary_value_id
            if item.get("evidence"):
                normalized_item["evidence"] = item["evidence"]
            if item.get("confidence") is not None:
                normalized_item["confidence"] = item["confidence"]
            normalized.append(normalized_item)
        return normalized

    @staticmethod
    def _merge_workbench_attributes(base_attrs: list[dict], override_attrs: list[dict]) -> list[dict]:
        merged: dict[int, dict] = {}
        order: list[int] = []
        for attr in base_attrs + override_attrs:
            try:
                attr_id = int(attr.get("attribute_id") or attr.get("id"))
            except (TypeError, ValueError):
                continue
            if attr_id not in merged:
                order.append(attr_id)
            merged[attr_id] = dict(attr, attribute_id=attr_id)
        return [merged[attr_id] for attr_id in order]

    def _append_lifecycle(self, skc: str, store_id: str, event: dict):
        """追加生命周期事件到草稿"""
        if not skc or not store_id:
            return
        draft = self._draft_repo.find_by_skc_store(skc, store_id)
        if draft is None:
            draft = ListingDraft(skc=skc, store_id=store_id)
        draft.append_lifecycle_event(event)
        self._draft_repo.save(draft)

    def _default_skus_from_product(self, skc: str, price: str) -> list[dict]:
        """从产品数据构建默认 SKU 列表"""
        product = self._find_product_by_skc(skc)
        if not product:
            return []
        result: list[dict] = []
        default_price = str(price or product.get("price") or "")
        for sku in product.get("skus") or []:
            result.append({
                "name": sku,
                "sku_code": sku,
                "price": default_price,
                "old_price": "",
                "stock": "10000",
                "barcode": "",
                "images": [],
            })
        return result

    def _find_product_by_skc(self, skc: str) -> dict | None:
        if not skc:
            return None
        products = self._product_facade.list_products()
        for product in products:
            if product.get("skc") == skc:
                return product
        return None

    @staticmethod
    def _extract_input_image_urls(images: list) -> list[str]:
        from ..domain.services import _extract_public_image_urls
        return _extract_public_image_urls(images, 10)

    @staticmethod
    def _default_wallet_title(product: dict, offer_id: str) -> str:
        text = str(product.get("title") or "")
        color = "черный" if "black" in (text + " " + offer_id).lower() else ""
        suffix = f", {color}" if color else ""
        return f"Кошелек Bostanten {offer_id.replace('-BLACK', '')}{suffix}".strip()

    @staticmethod
    def _default_wallet_description(product: dict) -> str:
        product_data = product.get("product_data", {}) or {}
        source_text = " ".join(
            str(product_data.get(key, ""))
            for key in ("about_item", "product_description", "description")
        ).strip()
        if len(source_text) >= 300:
            return source_text[:1800]
        return (
            "Женский кошелек Bostanten из прочного нейлона подходит для ежедневных дел, "
            "поездок и прогулок. Компактный формат удобно помещается в сумку, а съемный "
            "ремешок позволяет носить кошелек на запястье. Модель оснащена тремя "
            "отделениями на молнии, слотами для карт, карманом для монет и местом для "
            "документов. RFID-защита помогает снизить риск считывания банковских карт. "
            "Черный цвет и аккуратный дизайн легко сочетаются с повседневным стилем."
        )

    @staticmethod
    def _default_wallet_attributes(
        offer_id: str,
        title: str,
        description: str,
        product_data: dict,
        manual_data: dict,
        image_urls: list[str],
    ) -> list[dict]:
        brand = resolve_wallet_brand(product_data, manual_data)
        rich_value = rich_content_to_attribute_value(image_urls) if len(image_urls) >= 3 else json.dumps(
            build_wallet_rich_content([
                "https://example.com/1.png",
                "https://example.com/2.png",
                "https://example.com/3.png",
            ]),
            ensure_ascii=False,
        )
        weight = manual_data.get("weight_g") or manual_data.get("effective_weight_g") or "200"
        return [
            {
                "attribute_id": 85,
                "value": brand["value"],
                "dictionary_value_id": brand["dictionary_value_id"],
                "source": brand["source"],
            },
            {"attribute_id": 4180, "value": title, "source": "rule"},
            {"attribute_id": 4191, "value": description, "source": "rule"},
            {"attribute_id": 4383, "value": str(weight), "source": "rule"},
            {"attribute_id": 4384, "value": "Кошелек, съемный ремешок", "source": "rule"},
            {"attribute_id": 4389, "value": "Китай", "dictionary_value_id": 90296, "source": "rule"},
            {"attribute_id": 5299, "value": "17.1", "source": "rule"},
            {"attribute_id": 5309, "value": "Нейлон", "dictionary_value_id": 61965, "source": "rule"},
            {"attribute_id": 5311, "value": "Металл", "dictionary_value_id": 61936, "source": "rule"},
            {"attribute_id": 5313, "value": "Полиэстер", "dictionary_value_id": 62040, "source": "rule"},
            {"attribute_id": 5344, "value": "Молния", "dictionary_value_id": 60850, "source": "rule"},
            {"attribute_id": 5355, "value": "11.2", "source": "rule"},
            {"attribute_id": 6573, "value": "2.5", "source": "rule"},
            {"attribute_id": 8229, "value": "Кошелек", "dictionary_value_id": 93338, "source": "rule"},
            {"attribute_id": 9024, "value": offer_id, "source": "rule"},
            {"attribute_id": 9048, "value": offer_id.replace("-BLACK", ""), "source": "rule"},
            {"attribute_id": 9163, "value": "Женский", "dictionary_value_id": 22881, "source": "rule"},
            {"attribute_id": 9390, "value": "Взрослая", "dictionary_value_id": 43241, "source": "rule"},
            {"attribute_id": 9661, "value": "1", "source": "rule"},
            {"attribute_id": 9725, "value": "Базовая коллекция", "dictionary_value_id": 39116, "source": "rule"},
            {"attribute_id": 10096, "value": "черный", "dictionary_value_id": 61574, "source": "rule"},
            {"attribute_id": 10097, "value": "черный", "source": "rule"},
            {"attribute_id": 10400, "value": "Без гарантии", "dictionary_value_id": 970960203, "source": "rule"},
            {"attribute_id": 11254, "value": rich_value, "source": "rule"},
            {"attribute_id": 11650, "value": "1", "source": "rule"},
            {"attribute_id": 23171, "value": "#женский_кошелек #кошелек_на_молнии #rfid_защита #кошелек_на_запястье", "source": "rule"},
            {"attribute_id": 23249, "value": "1", "source": "rule"},
            {"attribute_id": 23287, "value": "Портмоне", "dictionary_value_id": 972848865, "source": "rule"},
        ]

    @staticmethod
    def _default_workbench_skus(product: dict, offer_id: str, price: str, submitted_skus: list) -> list[dict]:
        if submitted_skus:
            return submitted_skus
        skus = product.get("skus") or [offer_id]
        return [
            {"name": str(sku), "sku_code": str(sku), "price": price, "old_price": "", "stock": "10000", "barcode": "", "images": []}
            for sku in skus
        ]

    def _extract_item_dimensions(self, skc: str) -> tuple[int | None, int | None, int | None, int | None]:
        """从产品库提取重量(g)和尺寸(mm)，用于 Ozon item 层字段。
        返回: (weight_g, depth_mm, width_mm, height_mm)
        """
        product = self._find_product_by_skc(skc)
        if not product:
            return None, None, None, None

        manual = product.get("manual_data", {}) or {}

        # 重量(g): 优先 manual_data.weight_g, 其次 collected_weight_g
        weight = self._parse_weight_grams(manual.get("weight_g", ""))
        if weight is None:
            weight = self._parse_weight_grams(manual.get("collected_weight_g", ""))

        # 尺寸(mm): 优先 collected_size_cm, 转为 mm
        depth, width, height = self._parse_size_mm(manual)

        return weight, depth, width, height

    @staticmethod
    def _parse_weight_grams(raw: str) -> int | None:
        """解析重量字符串为克数，如 '200g', '200', '0.2 Pounds'"""
        if not raw:
            return None
        text = str(raw).strip().lower()
        # 匹配数字
        match = re.search(r"[\d.]+", text)
        if not match:
            return None
        val = float(match.group())
        if "pound" in text or "lb" in text:
            val = val * 453.592  # lb -> g
        if "ounce" in text or "oz" in text:
            val = val * 28.3495  # oz -> g
        return int(round(val))

    @staticmethod
    def _parse_size_mm(manual: dict) -> tuple[int | None, int | None, int | None]:
        """从 manual_data 解析尺寸，返回 (depth_mm, width_mm, height_mm)"""
        collected = manual.get("collected_size_cm") or []
        if isinstance(collected, list) and len(collected) >= 3:
            try:
                return (
                    int(round(float(collected[0]) * 10)),
                    int(round(float(collected[1]) * 10)),
                    int(round(float(collected[2]) * 10)),
                )
            except (ValueError, TypeError):
                pass
        size_spec = str(manual.get("collected_size_spec", ""))
        if size_spec:
            nums = re.findall(r"[\d.]+", size_spec)
            if len(nums) >= 3:
                try:
                    return (
                        int(round(float(nums[0]) * 10)),
                        int(round(float(nums[1]) * 10)),
                        int(round(float(nums[2]) * 10)),
                    )
                except (ValueError, TypeError):
                    pass
        return None, None, None

    @staticmethod
    def _format_ozon_attributes(attrs: list[dict]) -> list[dict]:
        ozon_attrs: list[dict] = []
        for attr in attrs:
            attr_id = attr.get("attribute_id")
            value = attr.get("value", "")
            attr_type = attr.get("type", "text")
            if not attr_id:
                continue
            entry: dict = {"id": int(attr_id), "values": []}
            # 字典值优先级: 显式 dictionary_value_id > 可解析为 int 的 value
            if "dictionary_value_id" in attr and attr["dictionary_value_id"] is not None:
                entry["values"].append({"dictionary_value_id": int(attr["dictionary_value_id"])})
            elif attr_type == "dictionary":
                try:
                    dict_val_id = int(value)
                    entry["values"].append({"dictionary_value_id": dict_val_id})
                except (ValueError, TypeError):
                    entry["values"].append({"value": str(value)})
            else:
                entry["values"].append({"value": str(value)})
            ozon_attrs.append(entry)
        return ozon_attrs

    @staticmethod
    def _build_ozon_items(
        skus: list[dict], name: str, price, offer_id: str, barcode: str,
        category_id, type_id, description: str,
        ozon_attrs: list[dict], base_image_urls: list[str],
        base_video_urls: list[str], images: list,
        weight: int | None = None,
        depth: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> list[dict]:
        from ..domain.services import _extract_public_image_urls

        items: list[dict] = []
        if skus:
            for sku in skus:
                sku_price = sku.get("price", "")
                sku_barcode_val = sku.get("barcode", "")
                sku_images = sku.get("images", [])
                sku_offer_id = sku.get("name", "") or offer_id
                if not sku_offer_id:
                    continue
                item = {
                    "name": name,
                    "offer_id": sku_offer_id,
                    "price": sku_price or price,
                    "currency_code": "CNY",
                    "description_category_id": int(category_id),
                    "attributes": ozon_attrs,
                    "vat": "0",
                }
                if weight is not None:
                    item["weight"] = weight
                    item["weight_unit"] = "g"
                if depth is not None:
                    item["depth"] = depth
                    item["dimension_unit"] = "mm"
                if width is not None:
                    item["width"] = width
                if height is not None:
                    item["height"] = height
                if type_id and str(type_id) != str(category_id):
                    item["type_id"] = int(type_id)
                if description:
                    item["description"] = description[:2000]
                if sku_barcode_val:
                    item["barcode"] = sku_barcode_val
                sku_urls = _extract_public_image_urls(sku_images, 10)
                item_images = sku_urls if sku_urls else base_image_urls
                if item_images:
                    item["images"] = item_images
                if base_video_urls:
                    item["videos"] = base_video_urls
                items.append(item)
        else:
            if not offer_id:
                return []
            item = {
                "name": name,
                "offer_id": offer_id,
                "price": price,
                "currency_code": "CNY",
                "description_category_id": int(category_id),
                "attributes": ozon_attrs,
                "vat": "0",
            }
            if weight is not None:
                item["weight"] = weight
                item["weight_unit"] = "g"
            if depth is not None:
                item["depth"] = depth
                item["dimension_unit"] = "mm"
            if width is not None:
                item["width"] = width
            if height is not None:
                item["height"] = height
            if type_id and str(type_id) != str(category_id):
                item["type_id"] = int(type_id)
            if description:
                item["description"] = description[:2000]
            if barcode:
                item["barcode"] = barcode
            if base_image_urls:
                item["images"] = base_image_urls
            if base_video_urls:
                item["videos"] = base_video_urls
            items.append(item)
        return items

    def _load_sync_state(self) -> dict:
        if os.path.exists(self._sync_state_file):
            try:
                with open(self._sync_state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_sync_state(self, store_id: str, matched: int):
        sync_state = self._load_sync_state()
        store_sync = sync_state.get(store_id, {})
        store_sync["last_sync"] = datetime.now().isoformat()
        store_sync["last_pull_matched"] = matched
        sync_state[store_id] = store_sync
        try:
            with open(self._sync_state_file, "w", encoding="utf-8") as f:
                json.dump(sync_state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
