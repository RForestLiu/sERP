import json

from src.serp.collect.application.commands import CollectApplicationService
from src.serp.collect.domain.entities import CollectTask


class FakeRepo:
    def __init__(self, task):
        self.task = task

    def find_by_id(self, task_id):
        return self.task if self.task.id == task_id else None


class FakeSettings:
    pass


class FakeBus:
    def publish(self, _event):
        pass


def test_failed_clean_clears_stale_cleaned_product_data(monkeypatch, tmp_path):
    product_file = tmp_path / "product_data.json"
    product_file.write_text(json.dumps({
        "product_data": {
            "cleaned_product_data": {"product_param": {"color": "красный"}},
            "images_mapping": {},
            "raw_product_data": {"title": "Wallet"},
        },
        "clean_status": {"status": "cleaning", "message": "cleaning"},
        "clean_audit": None,
    }, ensure_ascii=False), encoding="utf-8")

    task = CollectTask(id="collect_test", url="https://example.test", platform="wildberries")
    task.complete({"product_data": str(product_file), "images_mapping": "", "images_dir": str(tmp_path)})
    service = CollectApplicationService(FakeRepo(task), FakeSettings(), FakeBus(), str(tmp_path))

    class FailingCleaner:
        def __init__(self, _settings):
            pass

        def clean(self, _raw_data):
            return {
                "product_data": {"product_param": {}, "product_description": ""},
                "raw_product_data": {"title": "Wallet"},
                "clean_audit": {
                    "status": "review_failed",
                    "model": "deepseek-v4-pro",
                    "language": "English",
                    "error": "language_mismatch",
                },
            }

    monkeypatch.setattr(
        "src.serp.collect.infrastructure.product_data_cleaner.ProductDataCleaner",
        FailingCleaner,
    )

    service._run_product_clean(task.id)
    package = json.loads(product_file.read_text(encoding="utf-8"))

    assert package["clean_status"]["status"] == "failed"
    assert package["product_data"]["cleaned_product_data"] is None
