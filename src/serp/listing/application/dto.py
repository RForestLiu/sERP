"""
Listing 域 - 应用层 DTO。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DraftViewDTO:
    """草稿视图 DTO"""
    exists: bool = False
    listing: dict | None = None


@dataclass
class ListingSimulateDTO:
    """模拟上架结果 DTO"""
    success: bool = True
    store_id: str = ""
    skc: str = ""
    report: dict = field(default_factory=dict)


@dataclass
class ProductCreateDTO:
    """产品创建结果 DTO"""
    success: bool = False
    task_id: str = ""
    skc: str = ""
    item_count: int = 0
    quality_report: dict = field(default_factory=dict)
    message: str = ""
    error: str = ""


@dataclass
class SyncResultDTO:
    """同步结果 DTO"""
    success: bool = False
    total_ozon_products: int = 0
    matched: int = 0
    new_skus: int = 0
    updated: int = 0
    synced_products: list[dict] = field(default_factory=list)
    last_sync: str = ""
    message: str = ""


@dataclass
class AutoFillAnalyzeDTO:
    """店小秘自动填充分析结果 DTO"""
    success: bool = True
    skc: str = ""
    mappings: list[dict] = field(default_factory=list)
    total_fields: int = 0
    filled_fields: int = 0
    error: str = ""


@dataclass
class AutoFillOzonFieldsDTO:
    """Ozon 属性自动填充结果 DTO"""
    success: bool = True
    skc: str = ""
    mappings: list[dict] = field(default_factory=list)
    total_attributes: int = 0
    filled_attributes: int = 0
    important_count: int = 0
    regular_count: int = 0
    preset_matched: int = 0
    non_required_presets: int = 0
    deterministic_hints: list[str] = field(default_factory=list)
    error: str = ""
