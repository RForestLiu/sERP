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

        # 格式化属性
        ozon_attrs = self._format_ozon_attributes(attrs)

        # 图片和视频
        from ..domain.services import _extract_public_image_urls
        base_image_urls = _extract_public_image_urls(images, 10)
        base_video_urls = [v.get("url", "") for v in videos if v.get("url", "").startswith("http")]

        # 构建 items
        items = self._build_ozon_items(
            skus=skus, name=name, price=price, offer_id=offer_id,
            barcode=barcode, category_id=category_id, type_id=type_id,
            description=description, ozon_attrs=ozon_attrs,
            base_image_urls=base_image_urls, base_video_urls=base_video_urls,
            images=images,
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

    # ==================== AI 填充 ====================

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
    def _format_ozon_attributes(attrs: list[dict]) -> list[dict]:
        ozon_attrs: list[dict] = []
        for attr in attrs:
            attr_id = attr.get("attribute_id")
            value = attr.get("value", "")
            attr_type = attr.get("type", "text")
            if not attr_id:
                continue
            entry: dict = {"id": int(attr_id), "values": []}
            if attr_type == "dictionary":
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
