from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient


def test_form_field_summary_includes_dianxiaomi_runtime_metadata():
    fields = [{
        "index": 7,
        "label": "材料",
        "tag": "select",
        "type": "select",
        "controlKind": "ant-select-search",
        "dxmAttribute": {
            "sourceGroup": "attrsList",
            "attributeId": "5309",
            "name": "Материал",
            "nameCn": "材料",
            "type": "String",
            "collection": 1,
            "required": 1,
            "dictionaryId": "321",
            "optionsNum": 100,
            "maxValueCount": 3,
            "dxmControlKind": "dictionary-multiple-remote",
        },
    }]

    summary, _, _ = DeepSeekAutoFillClient._build_form_fields_summary(fields)

    assert "DXM属性ID: 5309" in summary
    assert "DXM控件: dictionary-multiple-remote" in summary
    assert "字典ID: 321" in summary
    assert "多值: 1" in summary


def test_form_field_summary_includes_ozon_api_attribute_metadata():
    fields = [{
        "index": 4,
        "label": "原产国",
        "tag": "checkbox-group",
        "type": "checkbox",
        "ozonAttribute": {
            "id": 4389,
            "name": "Страна-изготовитель",
            "name_cn": "原产国",
            "type": "dictionary",
            "dictionary_id": 971082156,
            "is_required": True,
            "is_collection": False,
            "max_value_count": 1,
        },
    }]

    summary, _, _ = DeepSeekAutoFillClient._build_form_fields_summary(fields)

    assert "Ozon属性ID: 4389" in summary
    assert "Ozon类型: dictionary" in summary
    assert "Ozon字典ID: 971082156" in summary
    assert "Ozon名称: 原产国/Страна-изготовитель" in summary


def test_form_field_summary_includes_ozon_dictionary_values():
    fields = [{
        "index": 4,
        "label": "原产国",
        "tag": "select",
        "type": "select",
        "ozonAttribute": {
            "id": 4389,
            "name": "Страна-изготовитель",
            "name_cn": "原产国",
            "type": "dictionary",
            "dictionary_id": 971082156,
            "dictionary_values": [
                {"id": 970674898, "value": "Китай", "value_cn": "中国"},
                {"id": 970674899, "value": "Россия", "value_cn": "俄罗斯"},
            ],
        },
    }]

    summary, _, _ = DeepSeekAutoFillClient._build_form_fields_summary(fields)

    assert "Ozon官方候选" in summary
    assert "中国(Китай)" in summary
    assert "俄罗斯(Россия)" in summary
    assert "字典字段只能返回 Ozon官方候选之一" in summary
