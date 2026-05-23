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
    def __init__(self):
        self.value_translations = {}
        self.saved_value_translations = []

    def load_names(self, store_id):
        return {"Материал": "材质", "Крышка в комплекте": "含盖子"}

    def save_names(self, store_id, translations):
        pass

    def load_descriptions(self, store_id):
        return {}

    def save_descriptions(self, store_id, translations):
        pass

    def load_values(self, store_id):
        return dict(self.value_translations)

    def save_values(self, store_id, translations):
        self.value_translations = dict(translations)
        self.saved_value_translations.append(dict(translations))


class FakeExcludedRepo:
    def load(self, store_id):
        return set()

    def add(self, store_id, category_id):
        pass


class FakeLlm:
    def __init__(self):
        self.calls = []

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
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
    assert by_id[5309]["dictionary_values"] == [{"id": 61965, "value": "Нейлон", "value_cn": "尼龙"}]
    assert by_id[999]["dictionary_values"] == [
        {"id": 1, "value": "Да", "value_cn": "是"},
        {"id": 2, "value": "Нет", "value_cn": "否"},
    ]
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


def test_category_attribute_value_translations_are_cached():
    api = FakeOzonApi()
    attr_repo = FakeAttrTranslationRepo()
    service = OzonCategoryApplicationService(
        tree_cache_repo=FakeTreeRepo(),
        trans_cache_repo=FakeTranslationRepo(),
        attr_trans_cache_repo=attr_repo,
        excluded_repo=FakeExcludedRepo(),
        ozon_api=api,
        llm_client=FakeLlm(),
    )

    service.get_category_attributes("ozon_anling", 17027904, 93338)
    save_count_after_first_load = len(attr_repo.saved_value_translations)
    service.get_category_attributes("ozon_anling", 17027904, 93338)

    assert attr_repo.value_translations["Нейлон"] == "尼龙"
    assert attr_repo.value_translations["Да"] == "是"
    assert attr_repo.value_translations["Нет"] == "否"
    assert len(attr_repo.saved_value_translations) == save_count_after_first_load


def test_attribute_translation_prompt_includes_ozon_operator_context():
    api = FakeOzonApi()
    llm = FakeLlm()
    service = OzonCategoryApplicationService(
        tree_cache_repo=FakeTreeRepo(),
        trans_cache_repo=FakeTranslationRepo(),
        attr_trans_cache_repo=FakeAttrTranslationRepo(),
        excluded_repo=FakeExcludedRepo(),
        ozon_api=api,
        llm_client=llm,
    )

    service._translate_attr_names("ozon_anling", ["Тип застежки"])
    service._translate_attr_descs("ozon_anling", ["Выберите материал товара"])

    prompts = "\n".join(args[0] + "\n" + args[1] for args, _ in llm.calls)
    assert "Ozon" in prompts
    assert "中国运营人员" in prompts
    assert "属性表单" in prompts
