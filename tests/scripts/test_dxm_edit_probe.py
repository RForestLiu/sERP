import importlib.util
from pathlib import Path


def load_probe_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "dxm_edit_probe.py"
    spec = importlib.util.spec_from_file_location("dxm_edit_probe", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_product_id_from_edit_url():
    probe = load_probe_module()

    product_id = probe.extract_product_id(
        "https://www.dianxiaomi.com/web/ozonProduct/edit?id=16653546877261308"
    )

    assert product_id == "16653546877261308"


def test_summarize_product_payload_keeps_dxm_ozon_binding_fields():
    probe = load_probe_module()
    response = {
        "code": 0,
        "data": {
            "product": {
                "id": "16653546877261308",
                "shopId": "7040853",
                "descriptionCategoryId": "17027904",
                "typeId": "93338",
                "newCategoryId": "17027904-93338",
                "name": "Wallet title",
                "attribute": '[{"id":"5309","complex_id":0,"values":[{"dictionary_value_id":61839,"value":"Eco leather"}]}]',
                "mergeAttribute": '[{"id":"9048","values":[{"value":"MODEL-1"}]}]',
                "content": '{"version":0.3,"content":[]}',
                "variantList": [{
                    "id": "sku-row-1",
                    "sku": "WALLET-0001-RED",
                    "quantity": 5,
                    "price": 104.06,
                    "salePrice": 34,
                    "mainImage": "https://example.test/main.jpg",
                    "images": "https://example.test/1.jpg;https://example.test/2.jpg",
                    "variantAttribute": '[{"id":"10096","values":[{"dictionary_value_id":972075614,"value":"Red"}]}]',
                    "warehouseInventory": '[{"quantity":5,"id":"warehouse-1"}]',
                }],
            },
            "categoryList": '["17027904-93338","17027904"]',
        },
    }

    summary = probe.summarize_product_response(response)

    assert summary["product"]["id"] == "16653546877261308"
    assert summary["category"] == {
        "descriptionCategoryId": "17027904",
        "typeId": "93338",
        "newCategoryId": "17027904-93338",
        "categoryList": ["17027904-93338", "17027904"],
    }
    assert summary["attributes"]["count"] == 1
    assert summary["attributes"]["items"][0]["id"] == "5309"
    assert summary["attributes"]["items"][0]["values"][0]["dictionary_value_id"] == 61839
    assert summary["rich_content"]["present"] is True
    assert summary["variants"]["count"] == 1
    assert summary["variants"]["items"][0]["sku"] == "WALLET-0001-RED"
    assert summary["variants"]["items"][0]["image_count"] == 2
    assert summary["variants"]["items"][0]["warehouseInventory"][0]["id"] == "warehouse-1"


def test_summarize_attrs_info_exposes_dianxiaomi_component_metadata():
    probe = load_probe_module()
    attrs_info = {
        "showRichJSON": True,
        "showDesc": True,
        "attrsList": [{
            "attributeId": "5309",
            "name": "Материал",
            "nameCn": "材质",
            "type": "String",
            "collection": 1,
            "required": 1,
            "dictionaryId": "321",
            "optionsNum": 100,
            "maxValueCount": 3,
            "_inputType": "select",
            "_compType": "remoteSelect",
            "_remoteSearch": True,
        }, {
            "attributeId": "5299",
            "name": "Length",
            "nameCn": "长度",
            "type": "Decimal",
            "collection": 0,
            "required": 0,
            "dictionaryId": "0",
            "_inputType": "input",
            "_compType": "inputNumber",
        }],
        "mergeAttrsList": [],
        "skuList": [],
    }

    summary = probe.summarize_attrs_info(attrs_info)

    assert summary["flags"]["showRichJSON"] is True
    assert summary["groups"]["attrsList"]["count"] == 2
    material = summary["groups"]["attrsList"]["items"][0]
    assert material["attributeId"] == "5309"
    assert material["controlKind"] == "dictionary-multiple-remote"
    assert material["dictionaryId"] == "321"
    length = summary["groups"]["attrsList"]["items"][1]
    assert length["controlKind"] == "number-input"


def test_store_snapshot_expression_compacts_attrs_info_before_transport():
    probe = load_probe_module()

    expression = probe.build_store_snapshot_expression(["ozonProductAddStore"])

    assert "compactAttrsInfo" in expression
    assert "item.attrsInfo = state.attrsInfo" not in expression
