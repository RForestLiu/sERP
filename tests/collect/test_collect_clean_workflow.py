import json
from io import BytesIO

from src.serp.collect.application.commands import CollectApplicationService
from src.serp.collect.domain.entities import CollectTask
from src.serp.collect.infrastructure.capture_engine import _image_bytes_to_jpg


class FakeRepo:
    def __init__(self, task):
        self.task = task

    def load_all(self):
        return {self.task.id: self.task}

    def save(self, task):
        self.task = task

    def save_all(self):
        pass

    def find_by_id(self, task_id):
        return self.task if self.task.id == task_id else None

    def delete(self, task_id):
        pass

    def list_completed(self):
        return [self.task]


class FakeSettings:
    def get_feature_model(self, _key):
        return "deepseek_v4_pro"

    def get_models(self):
        return [{
            "id": "deepseek_v4_pro",
            "base_url": "https://example.test/chat",
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-v4-pro",
        }]

    def get_view(self):
        return type("View", (), {"settings": {"product_clean_language": "English"}})()


class FakeBus:
    def publish(self, _event):
        pass


def make_service(tmp_path):
    product_file = tmp_path / "product_data.json"
    mapping_file = tmp_path / "images_mapping.json"
    product_file.write_text(json.dumps({
        "product_data": {
            "cleaned_product_data": None,
            "images_mapping": {},
            "raw_product_data": {"title": "Wallet", "product_details": {"weight": "200g"}},
        },
        "clean_status": {"status": "not_cleaned", "message": "未清洗"},
        "clean_audit": None,
    }, ensure_ascii=False), encoding="utf-8")
    mapping_file.write_text(json.dumps({"black": [{"file": "01.jpg"}]}, ensure_ascii=False), encoding="utf-8")
    task = CollectTask(id="collect_test", url="https://example.test", platform="wildberries")
    task.complete({
        "product_data": str(product_file),
        "images_mapping": str(mapping_file),
        "images_dir": str(tmp_path),
    })
    return CollectApplicationService(FakeRepo(task), FakeSettings(), FakeBus(), str(tmp_path)), task


def test_result_embeds_images_mapping_under_product_data(tmp_path):
    service, task = make_service(tmp_path)

    result = service.get_result(task.id)

    assert result["product_data"]["product_data"]["images_mapping"] == {"black": [{"file": "01.jpg"}]}
    assert result["product_data"]["product_data"]["raw_product_data"]["title"] == "Wallet"
    assert result["product_data"]["clean_status"]["status"] == "not_cleaned"


def test_clean_offline_marks_unavailable_without_cleaned_data(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    service, task = make_service(tmp_path)

    status = service.clean_product_data(task.id)
    result = service.get_result(task.id)

    assert status["status"] == "unavailable"
    assert result["product_data"]["product_data"]["cleaned_product_data"] is None
    assert result["product_data"]["product_data"]["raw_product_data"]["title"] == "Wallet"


def test_clean_duration_estimate_uses_recent_ema(tmp_path):
    service, _task = make_service(tmp_path)
    for seconds in [10, 20, 30]:
        service._record_clean_duration(seconds)

    estimate = service._estimate_clean_duration()

    assert estimate["sample_count"] == 3
    assert estimate["method"] == "ema_last_30"
    assert estimate["estimated_seconds"] == 22
    assert estimate["estimated_text"] == "预计约 22秒"


def test_clean_duration_history_keeps_latest_30(tmp_path):
    service, _task = make_service(tmp_path)
    for seconds in range(35):
        service._record_clean_duration(seconds)

    durations = service._load_clean_durations()

    assert len(durations) == 30
    assert durations[0] == 5
    assert durations[-1] == 34


def test_clean_duration_estimate_is_absent_without_history(tmp_path):
    service, _task = make_service(tmp_path)

    assert service._estimate_clean_duration() is None


def test_image_bytes_convert_to_jpg():
    from PIL import Image

    source = BytesIO()
    Image.new("RGBA", (2, 2), (255, 0, 0, 128)).save(source, format="WEBP")

    jpg = _image_bytes_to_jpg(source.getvalue())

    assert jpg[:2] == b"\xff\xd8"
    assert Image.open(BytesIO(jpg)).format == "JPEG"
