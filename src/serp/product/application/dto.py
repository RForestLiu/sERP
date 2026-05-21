"""
Product 域 - 应用层 DTO。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProductListDTO:
    """产品列表 DTO"""
    products: list[dict] = field(default_factory=list)
    stores: list[dict] = field(default_factory=list)


@dataclass
class ProductManualDTO:
    """手工数据 DTO"""
    weight_g: str = ""
    size_spec: str = ""
    spec: str = ""
    cost_price: str = ""


@dataclass
class CollectSpecsResultDTO:
    """采集规格结果 DTO"""
    success: bool = True
    skc: str = ""
    collected: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)


@dataclass
class AutoExtractResultDTO:
    """自动提取结果 DTO"""
    success: bool = True
    skc: str = ""
    extracted: dict = field(default_factory=dict)


@dataclass
class ExtractFromTextDTO:
    """从文本提取结果 DTO"""
    success: bool = True
    extracted: dict = field(default_factory=dict)


@dataclass
class ImageDTO:
    """图片 DTO"""
    success: bool = True
    skc: str = ""
    images: list[dict] = field(default_factory=list)
    image_sets: list[dict] = field(default_factory=list)


@dataclass
class ImageSetsDTO:
    """图片集 DTO"""
    success: bool = True
    skc: str = ""
    image_sets: dict = field(default_factory=dict)
    image_subsets: dict = field(default_factory=dict)


@dataclass
class UploadResultDTO:
    """上传结果 DTO"""
    success: bool = True
    skc: str = ""
    filename: str = ""
    url: str = ""
    entry: dict = field(default_factory=dict)
