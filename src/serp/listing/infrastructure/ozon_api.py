"""
Listing 域 - Ozon Seller API HTTP 客户端。
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Callable

import requests

logger = logging.getLogger(__name__)


class OzonApiClient:
    """Ozon Seller API 客户端 — 封装 HTTP 调用和凭证解析"""

    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self, get_credentials: Callable[[str], tuple[str, str]]):
        """
        get_credentials: store_id -> (client_id, api_key)
        返回原始（未掩码）的 Ozon API 凭证。
        """
        self._get_credentials = get_credentials

    def call(
        self,
        store_id: str,
        endpoint: str,
        payload: dict | None = None,
        method: str = "POST",
    ) -> tuple[Optional[dict], str]:
        """
        调用 Ozon Seller API。
        返回: (response_dict, error_message)
        成功: (dict, "")
        失败: (None, error_string)
        """
        t_start = time.time()

        client_id, api_key = self._get_credentials(store_id)
        if not client_id or not api_key:
            logger.error("[Ozon API] 店铺未配置凭证: %s", store_id)
            return None, "店铺未配置 Ozon API 凭证"

        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
            "Content-Type": "application/json",
        }

        payload_desc = ""
        if payload:
            if "description_category_id" in payload:
                payload_desc = f" | category_id={payload['description_category_id']}"
            elif "attribute_id" in payload:
                payload_desc = f" | attr_id={payload['attribute_id']}"

        logger.info("[Ozon API] %s %s%s | store=%s", method, endpoint, payload_desc, store_id)

        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=30)
            else:
                resp = requests.post(url, headers=headers, json=payload or {}, timeout=30)

            elapsed = time.time() - t_start
            logger.info("[Ozon API] 响应 %s | 耗时 %.1fs | 大小 %s bytes",
                        resp.status_code, elapsed, len(resp.content))

            if resp.status_code != 200:
                logger.error("[Ozon API] 错误: HTTP %s: %s", resp.status_code, resp.text[:300])
                return None, f"Ozon API Error {resp.status_code}: {resp.text[:500]}"

            return resp.json(), ""
        except Exception as e:
            logger.error("[Ozon API] 异常: %s | 耗时 %.1fs", e, time.time() - t_start)
            return None, str(e)

    def import_info(self, store_id: str, task_id: str) -> tuple[dict | None, str]:
        """查询 Ozon 导入任务状态。调用 POST /v1/product/import/info"""
        payload = {"task_id": task_id}
        return self.call(store_id, "/v1/product/import/info", payload)

    def content_rating_by_sku(self, store_id: str, skus: list[str]) -> tuple[dict | None, str]:
        """Query Ozon content rating. POST /v1/product/rating-by-sku."""
        payload = {"skus": [str(s).strip() for s in skus if str(s).strip()]}
        return self.call(store_id, "/v1/product/rating-by-sku", payload)
