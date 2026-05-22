"""
Listing 域 - JSON 文件仓储实现。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from src.serp.shared import JsonFileStore

from ..domain.entities import ListingDraft
from ..domain.repositories import ListingDraftRepository

logger = logging.getLogger(__name__)


class JsonListingDraftRepository(ListingDraftRepository):
    """JSON 文件上架草稿仓储 — 每个草稿对应一个 JSON 文件"""

    def __init__(self, listings_dir: str):
        self._dir = listings_dir
        os.makedirs(self._dir, exist_ok=True)

    def _filepath(self, skc: str, store_id: str) -> str:
        return os.path.join(self._dir, f"{skc}_{store_id}.json")

    def find_by_skc_store(self, skc: str, store_id: str) -> Optional[ListingDraft]:
        path = self._filepath(skc, store_id)
        store = JsonFileStore(path)
        data = store.read()
        if data is None:
            return None
        return ListingDraft.from_dict(skc, store_id, data)

    def save(self, draft: ListingDraft):
        path = self._filepath(draft.skc, draft.store_id)
        store = JsonFileStore(path)
        store.write(draft.to_dict())

    def delete_by_skc_store(self, skc: str, store_id: str):
        path = self._filepath(skc, store_id)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
