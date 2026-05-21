"""
Product 域 - 实体与聚合根。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.serp.shared import AggregateRoot, Entity, DomainError

from .value_objects import ManualData, StoreStatusEntry, ImageSetEntry
from .events import (
    ProductDeleted,
    ProductManualUpdated,
    SpecsCollected,
    ProductAutoExtracted,
    StoreStatusChanged,
    ImageSetsUpdated,
    ProductImageUploaded,
    ProductVideoUploaded,
)


@dataclass
class Product(AggregateRoot):
    """产品聚合根 — SKC 是全局唯一标识"""

    title: str = ""
    platform: str = ""
    category: str = ""
    product_data: dict = field(default_factory=dict)
    _manual: ManualData = field(default_factory=ManualData, repr=False)
    _store_status: dict[str, str] = field(default_factory=dict, repr=False)
    thumbnail: str = ""
    images_dir: str = ""
    images: list[dict] = field(default_factory=list, repr=False)
    video_url: str = ""
    _image_sets: dict[str, list[dict]] = field(default_factory=dict, repr=False)
    _image_subsets: dict[str, dict[str, list[dict]]] = field(default_factory=dict, repr=False)
    created_at: str = ""
    updated_at: str = ""

    # id 字段映射到 skc
    @property
    def skc(self) -> str:
        return self.id

    @skc.setter
    def skc(self, value: str):
        self.id = value

    def __post_init__(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = self.created_at

    # ── 属性访问 ──

    @property
    def manual_data(self) -> ManualData:
        return self._manual

    @property
    def store_status(self) -> dict[str, str]:
        return dict(self._store_status)

    @property
    def image_sets(self) -> dict[str, list[dict]]:
        return dict(self._image_sets)

    @property
    def image_subsets(self) -> dict[str, dict[str, list[dict]]]:
        return dict(self._image_subsets)

    # ── 业务行为 ──

    def update_manual(self, weight_g: str = "", size_spec: str = "",
                      spec: str = "", cost_price: str = ""):
        """更新手工登记数据"""
        self._manual = self._manual.with_updates(
            weight_g=weight_g,
            size_spec=size_spec,
            spec=spec,
            cost_price=cost_price,
        )
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_domain_event(ProductManualUpdated(
            skc=self.skc,
            changes={"weight_g": weight_g, "size_spec": size_spec, "spec": spec, "cost_price": cost_price},
        ))

    def set_collected_specs(self, weight_g, size_spec: str, size_cm: list[float],
                            evidence: dict, review: dict):
        """设置 LLM 采集的规格数据"""
        self._manual = self._manual.with_collected_specs(
            weight_g=weight_g,
            size_spec=size_spec,
            size_cm=size_cm,
            evidence=evidence,
            review=review,
        )
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_domain_event(SpecsCollected(
            skc=self.skc,
            weight_g=str(weight_g) if weight_g else "",
            size_spec=size_spec,
        ))

    def mark_auto_extracted(self, fields: list[str]):
        """标记自动提取完成"""
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_domain_event(ProductAutoExtracted(skc=self.skc, fields=fields))

    def update_store_status(self, store_id: str, new_status: str):
        """更新单店铺上架状态"""
        if not StoreStatusEntry.is_valid_status(new_status):
            raise DomainError(f"Invalid store status: {new_status}")
        old_status = self._store_status.get(store_id, "未上架")
        self._store_status[store_id] = new_status
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_domain_event(StoreStatusChanged(
            skc=self.skc, store_id=store_id,
            old_status=old_status, new_status=new_status,
        ))

    def set_thumbnail(self, path: str):
        """设置缩略图"""
        self.thumbnail = path

    def update_image_sets(self, sets: dict[str, list[dict]], subsets: dict[str, dict[str, list[dict]]] = None):
        """替换全部 image_sets"""
        self._image_sets = sets or {}
        if subsets is not None:
            self._image_subsets = subsets
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_domain_event(ImageSetsUpdated(skc=self.skc, set_count=len(self._image_sets)))

    def add_image_to_set(self, set_name: str, entry: dict):
        """向指定图片集添加一条记录"""
        if set_name not in self._image_sets:
            self._image_sets[set_name] = []
        entry["index"] = len(self._image_sets[set_name])
        self._image_sets[set_name].append(entry)
        self.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_domain_event(ProductImageUploaded(
            skc=self.skc,
            filename=entry.get("filename", ""),
            set_name=set_name,
        ))

    def set_video_url(self, url: str):
        """设置视频 URL"""
        self.video_url = url

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "skc": self.skc,
            "title": self.title,
            "platform": self.platform,
            "category": self.category,
            "product_data": self.product_data,
            "manual_data": self._manual.to_dict(),
            "store_status": dict(self._store_status),
            "thumbnail": self.thumbnail,
            "images_dir": self.images_dir,
            "images": self.images,
            "video_url": self.video_url,
            "image_sets": dict(self._image_sets),
            "image_subsets": dict(self._image_subsets),
        }

    def to_view(self, store_ids: list[str] = None) -> dict:
        """视图序列化（回填 store_status 等）"""
        status = dict(self._store_status)
        if store_ids:
            for sid in store_ids:
                if sid not in status:
                    status[sid] = "未上架"
        return {
            "skc": self.skc,
            "title": self.title,
            "platform": self.platform,
            "category": self.category,
            "product_data": self.product_data,
            "manual_data": self._manual.to_dict(),
            "store_status": status,
            "thumbnail": self.thumbnail,
            "images_dir": self.images_dir,
            "images": self.images,
            "video_url": self.video_url,
            "image_sets": dict(self._image_sets),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Product":
        md = data.get("manual_data", {}) if isinstance(data.get("manual_data"), dict) else {}
        manual = ManualData.from_dict(md)
        return cls(
            id=data.get("skc", ""),
            title=data.get("title", ""),
            platform=data.get("platform", ""),
            category=data.get("category", ""),
            product_data=data.get("product_data", {}) if isinstance(data.get("product_data"), dict) else {},
            _manual=manual,
            _store_status=data.get("store_status", {}) if isinstance(data.get("store_status"), dict) else {},
            thumbnail=data.get("thumbnail", ""),
            images_dir=data.get("images_dir", ""),
            images=data.get("images", []) if isinstance(data.get("images"), list) else [],
            video_url=data.get("video_url", ""),
            _image_sets=data.get("image_sets", {}) if isinstance(data.get("image_sets"), dict) else {},
            _image_subsets=data.get("image_subsets", {}) if isinstance(data.get("image_subsets"), dict) else {},
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ProductCollection:
    """产品集合 — 管理产品的加载/保存/查询，不是聚合根，只是容器。"""

    def __init__(self, registered: dict[str, str] = None, products: list[Product] = None):
        self._registered: dict[str, str] = registered or {}
        self._products: dict[str, Product] = {}
        if products:
            for p in products:
                if p.skc:
                    self._products[p.skc] = p

    @property
    def products(self) -> list[Product]:
        return list(self._products.values())

    @property
    def registered_numbers(self) -> dict[str, str]:
        return dict(self._registered)

    def find_by_skc(self, skc: str) -> Optional[Product]:
        return self._products.get(skc)

    def add_or_update(self, product: Product):
        self._products[product.skc] = product

    def remove(self, skc: str):
        self._products.pop(skc, None)
        self._registered.pop(skc, None)

    def register_number(self, skc: str, number: str):
        self._registered[skc] = number

    def to_dict(self) -> dict:
        return {
            "已注册编号": dict(self._registered),
            "产品列表": [p.to_dict() for p in self.products],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProductCollection":
        registered = data.get("已注册编号", {}) if isinstance(data, dict) else {}
        products_raw = data.get("产品列表", []) if isinstance(data, dict) else []
        products = [Product.from_dict(p) for p in products_raw if isinstance(p, dict)]
        return cls(registered=registered, products=products)
