from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient


def test_form_field_summary_includes_dianxiaomi_runtime_metadata():
    fields = [{
        "index": 7,
        "label": "材质",
        "tag": "select",
        "type": "select",
        "controlKind": "ant-select-search",
        "dxmAttribute": {
            "sourceGroup": "attrsList",
            "attributeId": "5309",
            "name": "Материал",
            "nameCn": "材质",
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
