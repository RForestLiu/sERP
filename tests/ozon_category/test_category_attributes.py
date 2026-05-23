from src.serp.ozon_category.application.commands import OzonCategoryApplicationService


class FakeTreeRepo:
    def load(self, store_id):
        return None

    def save(self, store_id, tree):
        pass


class FakeTranslationRepo:
    def load(self, store_id):
        return {}

    def save(self, store_id, translations):
        pass

    def update(self, store_id, new_translations):
        pass


class FakeAttrTranslationRepo:
    def load_names(self, store_id):
        return {"Материал": "材质", "Крышка в комплекте": "含盖子"}

    def save_names(self, store_id, translations):
        pass

    def load_descriptions(self, store_id):
        return {}

    def save_descriptions(self, store_id, translations):
        pass


class FakeExcludedRepo:
    def load(self, store_id):
        return set()

    def add(self, store_id, category_id):
        pass


class FakeLlm:
    def call(self, *args, **kwargs):
        return {"choices": [{"message": {"content": "{}"}}]}, ""


class FakeOzonApi:
    def __init__(self):
        self.calls = []

    def call(self, store_id, endpoint, payload=None, method="POST"):
        self.calls.append((endpoint, payload or {}))
        if endpoint == "/v1/description-category/attribute":
            return {
                "result": [
                    {
                        "id": 5309,
                        "name": "Материал",
                        "type": "String",
                        "is_collection": True,
                        "dictionary_id": 1503,
                        "max_value_count": 0,
                    },
                    {
                        "id": 999,
                        "name": "Крышка в комплекте",
                        "type": "String",
                        "is_collection": False,
                        "dictionary_id": 321,
                        "max_value_count": 1,
                    },
                    {
                        "id": 4180,
                        "name": "Название модели",
                        "type": "String",
                        "is_collection": False,
                        "dictionary_id": 0,
                    },
                ]
            }, ""
        if endpoint == "/v1/description-category/attribute/values":
            attr_id = payload["attribute_id"]
            if attr_id == 5309:
                return {"result": [{"id": 61965, "value": "Нейлон"}], "has_next": False}, ""
            if attr_id == 999:
                return {"result": [{"id": 1, "value": "Да"}, {"id": 2, "value": "Нет"}], "has_next": False}, ""
        return {}, ""


def make_service(api):
    return OzonCategoryApplicationService(
        tree_cache_repo=FakeTreeRepo(),
        trans_cache_repo=FakeTranslationRepo(),
        attr_trans_cache_repo=FakeAttrTranslationRepo(),
        excluded_repo=FakeExcludedRepo(),
        ozon_api=api,
        llm_client=FakeLlm(),
    )


def test_category_attributes_load_values_for_string_dictionary_attributes():
    api = FakeOzonApi()
    service = make_service(api)

    result = service.get_category_attributes("ozon_anling", 17027904, 93338)

    by_id = {attr["id"]: attr for attr in result["attributes"]}
    assert by_id[5309]["dictionary_id"] == 1503
    assert by_id[5309]["dictionary_values"] == [{"id": 61965, "value": "Нейлон"}]
    assert by_id[999]["dictionary_values"] == [{"id": 1, "value": "Да"}, {"id": 2, "value": "Нет"}]
    assert by_id[4180]["dictionary_values"] == []


def test_category_attribute_values_are_cached():
    api = FakeOzonApi()
    service = make_service(api)

    service.get_category_attributes("ozon_anling", 17027904, 93338)
    first_value_call_count = sum(1 for endpoint, _ in api.calls if endpoint.endswith("/attribute/values"))
    service.get_category_attributes("ozon_anling", 17027904, 93338)
    second_value_call_count = sum(1 for endpoint, _ in api.calls if endpoint.endswith("/attribute/values"))

    assert first_value_call_count == 2
    assert second_value_call_count == first_value_call_count
