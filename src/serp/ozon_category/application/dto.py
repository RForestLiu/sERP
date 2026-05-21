"""
OzonCategory 域 - 应用层 DTO。
"""
from dataclasses import dataclass, field


@dataclass
class CategoryTreeDTO:
    """品类树查询结果"""
    store_id: str = ""
    tree: list[dict] = field(default_factory=list)
    excluded_ids: list[int] = field(default_factory=list)
    node_count: int = 0


@dataclass
class TranslationResultDTO:
    """翻译结果"""
    translations: list[dict] = field(default_factory=list)
    translated_count: int = 0
    total_categories: int = 0


@dataclass
class RefreshStatusDTO:
    """刷新进度"""
    status: str = "idle"  # idle | running | completed | error
    progress: int = 0
    message: str = ""
    total_groups: int = 0
    current_group: int = 0
    total_nodes: int = 0
    translated: int = 0
    need_translate: int = 0
    error: str = ""


@dataclass
class CategoryMatchDTO:
    """品类匹配结果"""
    category_id: int = 0
    type_id: int | None = None
    category_name: str = ""
    path: str = ""
    node_path_names: list[str] = field(default_factory=list)
    node_path_ids: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0
    elapsed: float = 0


@dataclass
class CategoryAttributesDTO:
    """品类属性查询结果"""
    description_category_id: int = 0
    attributes: list[dict] = field(default_factory=list)
    is_leaf: bool = False
    warning: str = ""
    suggestions: list[dict] = field(default_factory=list)
