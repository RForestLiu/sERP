"""
Listing 域 - 仓储抽象接口。
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from src.serp.shared import Repository

from .entities import ListingDraft


class ListingDraftRepository(Repository[ListingDraft, str]):
    """上架草稿仓储"""

    @abstractmethod
    def find_by_skc_store(self, skc: str, store_id: str) -> Optional[ListingDraft]:
        """按 SKC + store_id 查找草稿"""
        ...

    @abstractmethod
    def save(self, draft: ListingDraft):
        """保存草稿"""
        ...

    @abstractmethod
    def delete_by_skc_store(self, skc: str, store_id: str):
        """按 SKC + store_id 删除草稿"""
        ...

    def find_by_id(self, id: str) -> Optional[ListingDraft]:
        # Composite ID: skc_store_id
        parts = id.split("_", 1)
        if len(parts) == 2:
            return self.find_by_skc_store(parts[0], parts[1])
        return None

    def delete(self, id: str):
        parts = id.split("_", 1)
        if len(parts) == 2:
            self.delete_by_skc_store(parts[0], parts[1])
