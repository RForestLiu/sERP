"""
Logistics 域 - 应用层 DTO。
"""
from dataclasses import dataclass, field


@dataclass
class TemplateSummaryDTO:
    """模板摘要"""
    templates: list[dict] = field(default_factory=list)


@dataclass
class CalculateResultDTO:
    """运费计算结果"""
    matched: bool
    best: dict = field(default_factory=dict)
    channels: list[dict] = field(default_factory=list)
    template_name: str = ""
    message: str = ""
