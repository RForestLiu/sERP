"""
Collect 域 - 应用层 DTO。
"""
from dataclasses import dataclass, field


@dataclass
class TaskListDTO:
    """任务列表 DTO"""
    tasks: list[dict] = field(default_factory=list)


@dataclass
class TaskStartDTO:
    """启动采集 DTO"""
    task_id: str = ""
    status: str = "pending"
    message: str = ""


@dataclass
class TaskStatusDTO:
    """任务状态 DTO"""
    task_id: str = ""
    status: str = ""
    progress: int = 0
    message: str = ""
    result: dict = field(default_factory=dict)


@dataclass
class TaskResultDTO:
    """采集结果 DTO"""
    task_id: str = ""
    summary: dict = field(default_factory=dict)
    product_data: dict = field(default_factory=dict)
    images_mapping: list = field(default_factory=list)
    thumbnail_urls: list[str] = field(default_factory=list)
    variant_groups: dict = field(default_factory=dict)


@dataclass
class CaptureResultDTO:
    """捕获结果 DTO"""
    status: str = "ok"
    task_id: str = ""
    title: str = ""
    platform: str = ""
    image_count: int = 0
    variant_count: int = 0


@dataclass
class SaveProductDTO:
    """产品保存 DTO"""
    success: bool = True
    skc: str = ""
    skus: list[str] = field(default_factory=list)
    category: str = ""
    message: str = ""


@dataclass
class ProductStatusDTO:
    """产品转换状态 DTO"""
    saved: bool = False
    skc: str = ""
    skus: list[str] = field(default_factory=list)
    category: str = ""
    title: str = ""


@dataclass
class DeleteTaskDTO:
    """删除任务 DTO"""
    success: bool = True
    task_id: str = ""
    message: str = ""


@dataclass
class OpenFolderDTO:
    """打开文件夹 DTO"""
    status: str = "opened"
    folder: str = ""


@dataclass
class SaveHtmlDTO:
    """HTML 快照保存 DTO"""
    status: str = "ok"
    filename: str = ""
    size: int = 0
