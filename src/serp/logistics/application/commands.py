"""
Logistics 域 - 应用服务（用例编排）。
"""
import logging

from ..facade import LogisticsFacade
from ..domain.entities import LogisticsTemplate
from ..domain.value_objects import ParcelSpec, MatchedChannel
from ..domain.services import ChannelMatchingService
from ..domain.repositories import LogisticsTemplateRepository
from .dto import CalculateResultDTO

logger = logging.getLogger(__name__)


class LogisticsApplicationService(LogisticsFacade):
    """Logistics 域应用服务"""

    def __init__(self, template_repo: LogisticsTemplateRepository):
        self._template_repo = template_repo

    def list_templates(self) -> list[dict]:
        templates = self._template_repo.load_all()
        return [t.to_summary() for t in templates]

    def calculate(self, data: dict) -> dict:
        template_id = data.get("template_id", "xingyuan_intl")
        weight_g = float(data.get("weight_g", 0))
        length_cm = float(data.get("length_cm", 0))
        width_cm = float(data.get("width_cm", 0))
        height_cm = float(data.get("height_cm", 0))
        value_rub = float(data.get("value_rub", 0))

        if weight_g <= 0:
            return {"error": "重量必须大于 0"}

        template = self._template_repo.find_by_id(template_id)
        if template is None:
            return {"error": f"物流模板不存在: {template_id}"}

        parcel = ParcelSpec(
            weight_g=weight_g,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            value_rub=value_rub,
        )

        matched = ChannelMatchingService.match(parcel, template.channels)

        if not matched:
            return {
                "matched": False,
                "message": "没有匹配的物流渠道，请检查重量、货值或尺寸参数",
                "channels": [],
            }

        best = matched[0]
        return {
            "matched": True,
            "best": best.to_dict(),
            "channels": [m.to_dict() for m in matched],
            "template_name": template.name,
        }
