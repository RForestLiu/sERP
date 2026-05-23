from src.serp.ozon_category.domain.entities import CategoryNode
from src.serp.ozon_category.application.commands import OzonCategoryApplicationService


def test_leaf_keeps_description_category_id_and_type_id_context():
    raw = {
        "description_category_id": 17027904,
        "category_name": "Кошелек",
        "type_id": None,
        "type_name": "Кошелек",
        "children": [
            {
                "type_id": 93338,
                "type_name": "Кошелек",
                "children": [],
            }
        ],
    }

    parent = CategoryNode.from_dict(raw)
    leaf = parent.children[0]

    assert parent.id == "17027904"
    assert parent.type_id == 0
    assert leaf.id == "93338"
    assert leaf.type_id == 93338
    assert getattr(leaf, "description_category_id") == 17027904


def test_leaf_candidate_payload_uses_category_id_plus_type_id():
    raw = {
        "description_category_id": 17027904,
        "category_name": "Кошелек",
        "children": [{"type_id": 93338, "type_name": "Кошелек", "children": []}],
    }
    parent = CategoryNode.from_dict(raw)
    leaf = parent.children[0]

    candidate = OzonCategoryApplicationService._candidate_from_node(
        leaf,
        translations={},
        parent_description_category_id=parent.description_category_id,
    )

    assert candidate["id"] == 93338
    assert candidate["description_category_id"] == 17027904
    assert candidate["type_id"] == 93338
    assert candidate["validation_id"] == 17027904
