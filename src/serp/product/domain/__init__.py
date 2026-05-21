"""
Product 域 - 核心层。
"""
from .entities import Product, ProductCollection
from .value_objects import ManualData, StoreStatusEntry, ImageRef, ImageSetEntry
from .events import (
    ProductCreated,
    ProductDeleted,
    ProductManualUpdated,
    SpecsCollected,
    ProductAutoExtracted,
    StoreStatusChanged,
    ImageSetsUpdated,
    ProductImageUploaded,
    ProductVideoUploaded,
)
from .repositories import ProductRepository

__all__ = [
    "Product",
    "ProductCollection",
    "ManualData",
    "StoreStatusEntry",
    "ImageRef",
    "ImageSetEntry",
    "ProductCreated",
    "ProductDeleted",
    "ProductManualUpdated",
    "SpecsCollected",
    "ProductAutoExtracted",
    "StoreStatusChanged",
    "ImageSetsUpdated",
    "ProductImageUploaded",
    "ProductVideoUploaded",
    "ProductRepository",
]
