from src.serp.listing.application.commands import ListingApplicationService


class FakeDraftRepo:
    def __init__(self):
        self.saved = {}

    def find_by_skc_store(self, skc, store_id):
        return self.saved.get((skc, store_id))

    def save(self, draft):
        self.saved[(draft.skc, draft.store_id)] = draft

    def delete_by_skc_store(self, skc, store_id):
        self.saved.pop((skc, store_id), None)


class FakeOzonApi:
    def __init__(self):
        self.calls = []

    def call(self, store_id, endpoint, payload=None, method="POST"):
        self.calls.append((endpoint, payload))
        if endpoint == "/v3/product/info/list":
            return {"items": [{"offer_id": "WALLET-0006-BLACK", "sources": [{"sku": 4408894048}]}]}, ""
        if endpoint == "/v1/product/rating-by-sku":
            return {"products": [{"sku": 4408894048, "rating": 77.5}]}, ""
        if endpoint == "/v3/product/import":
            return {"result": {"task_id": 123}}, ""
        return {}, ""

    def import_info(self, store_id, task_id):
        return {"result": {"items": []}}, ""

    def content_rating_by_sku(self, store_id, skus):
        return {"products": [{"sku": int(skus[0]), "rating": 77.5}]}, ""


class FakeAutoFill:
    is_configured = True

    def fill_ozon_attributes(self, skc, product_title, product_data, manual_data, ozon_attributes):
        return {
            "attributes": [{
                "attribute_id": 4180,
                "value": "AI title",
                "source": "llm_autofill",
            }]
        }


class FakeSettings:
    pass


class FakeProductFacade:
    def list_products(self):
        return [{
            "skc": "WALLET-0006",
            "title": "Bostanten wristlet wallet black",
            "price": "99.00",
            "skus": ["WALLET-0006-BLACK"],
            "product_data": {"brand": "Bostanten", "category": "wallet"},
            "manual_data": {"collected_size_cm": [2.5, 11.2, 17.1], "weight_g": "200"},
        }]


class FakeCategoryFacade:
    def match_category(self, store_id, product_info):
        return {
            "success": True,
            "best_match": {
                "id": 17027904,
                "type_id": 93338,
                "name": "Кошелек",
                "path": "Галантерея и аксессуары > Аксессуары > Кошелек",
                "reason": "AI selected the wallet category",
            },
        }

    def get_category_attributes(self, store_id, category_id, type_id=None):
        return {
            "success": True,
            "attributes": [{
                "id": 4180,
                "name": "Название модели",
                "type": "String",
                "is_required": True,
            }],
        }


class FakeCategoryFacadeNoMatch(FakeCategoryFacade):
    def match_category(self, store_id, product_info):
        return {
            "success": True,
            "best_match": None,
            "warning": "LLM 未返回可用匹配结果",
        }


class FakeBus:
    def publish(self, event):
        pass


def make_service():
    return ListingApplicationService(
        draft_repo=FakeDraftRepo(),
        ozon_api=FakeOzonApi(),
        autofill_client=FakeAutoFill(),
        settings_facade=FakeSettings(),
        product_facade=FakeProductFacade(),
        ozon_category_facade=FakeCategoryFacade(),
        event_bus=FakeBus(),
        data_root="data",
    )


def make_service_with_category(category_facade):
    return ListingApplicationService(
        draft_repo=FakeDraftRepo(),
        ozon_api=FakeOzonApi(),
        autofill_client=FakeAutoFill(),
        settings_facade=FakeSettings(),
        product_facade=FakeProductFacade(),
        ozon_category_facade=category_facade,
        event_bus=FakeBus(),
        data_root="data",
    )


def test_generate_workbench_draft_for_wallet():
    service = make_service()

    result = service.generate_workbench_draft("ozon_anling", {"skc": "WALLET-0006"})

    assert result["success"] is True
    assert result["draft"]["category_id"] == 17027904
    assert result["draft"]["type_id"] == 93338
    assert result["draft"]["category_attributes_count"] == 1
    assert result["validation"]["success"] is True
    assert any(attr["attribute_id"] == 11254 for attr in result["draft"]["attributes"])
    assert any(attr["attribute_id"] == 4180 and attr["value"] == "AI title" for attr in result["draft"]["attributes"])


def test_auto_category_fails_when_llm_returns_no_match():
    service = make_service_with_category(FakeCategoryFacadeNoMatch())

    result = service.auto_category("ozon_anling", {"skc": "WALLET-0006"})

    assert result["success"] is False
    assert result["error"] == "LLM 未返回可用匹配结果"
    assert "fallback" not in result


def test_official_rating_resolves_numeric_sku_before_rating_call():
    service = make_service()

    result = service.official_rating("ozon_anling", {"offer_id": "WALLET-0006-BLACK"})

    assert result["success"] is True
    assert result["skus"] == [4408894048]
    assert result["result"]["products"][0]["rating"] == 77.5
