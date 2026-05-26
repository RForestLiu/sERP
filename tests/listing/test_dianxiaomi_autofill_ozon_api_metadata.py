from src.serp.listing.application.commands import ListingApplicationService


class FakeDraftRepo:
    pass


class FakeOzonApi:
    pass


class FakeSettings:
    pass


class FakeProductFacade:
    pass


class FakeBus:
    def publish(self, event):
        pass


class CapturingAutoFill:
    is_configured = True

    def __init__(self):
        self.form_fields = None

    def analyze_dianxiaomi(
        self,
        skc,
        product_title,
        product_data,
        manual_data,
        form_fields,
        custom_prompts,
        variant_list,
        variant_row_summary,
    ):
        self.form_fields = form_fields
        return []


class FakeCategoryFacade:
    def __init__(self):
        self.calls = []

    def get_category_attributes(self, store_id, category_id, type_id=None):
        self.calls.append((store_id, category_id, type_id))
        return {
            "success": True,
            "attributes": [
                {
                    "id": 4389,
                    "name": "Страна-изготовитель",
                    "name_cn": "原产国",
                    "type": "dictionary",
                    "dictionary_id": 971082156,
                    "is_required": True,
                    "is_collection": False,
                    "max_value_count": 1,
                    "dictionary_values": [
                        {"id": 970674898, "value": "Китай", "value_cn": "中国"},
                        {"id": 970674899, "value": "Россия", "value_cn": "俄罗斯"},
                    ],
                }
            ],
        }


def make_service(autofill, category_facade):
    return ListingApplicationService(
        draft_repo=FakeDraftRepo(),
        ozon_api=FakeOzonApi(),
        autofill_client=autofill,
        settings_facade=FakeSettings(),
        product_facade=FakeProductFacade(),
        ozon_category_facade=category_facade,
        event_bus=FakeBus(),
        data_root="data",
    )


def test_dianxiaomi_autofill_enriches_fields_with_current_ozon_api_attributes():
    autofill = CapturingAutoFill()
    category_facade = FakeCategoryFacade()
    service = make_service(autofill, category_facade)

    result = service.analyze_for_autofill({
        "store_id": "ozon_anling",
        "category_context": {
            "description_category_id": 17027904,
            "type_id": 93338,
        },
        "form_fields": [{
            "index": 1,
            "label": "原产国",
            "dxmAttribute": {"attributeId": "4389"},
        }],
    })

    assert result["success"] is True
    assert category_facade.calls == [("ozon_anling", 17027904, 93338)]
    field = autofill.form_fields[0]
    assert field["ozonAttribute"]["id"] == 4389
    assert field["ozonAttribute"]["name_cn"] == "原产国"
    assert field["ozonAttribute"]["dictionary_id"] == 971082156
    assert field["ozonAttribute"]["dictionary_values"] == [
        {"id": 970674898, "value": "Китай", "value_cn": "中国"},
        {"id": 970674899, "value": "Россия", "value_cn": "俄罗斯"},
    ]
