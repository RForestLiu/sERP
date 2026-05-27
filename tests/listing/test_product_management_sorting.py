from src.serp.product.application.commands import ProductApplicationService
from src.serp.product.domain.entities import Product, ProductCollection


class FakeProductRepo:
    def load_all(self):
        return ProductCollection(products=[
            Product(id="OLD", title="Old", created_at="2026-05-20T10:00:00"),
            Product(id="NEW", title="New", created_at="2026-05-27T09:30:00"),
            Product(id="MID", title="Mid", created_at="2026-05-25 12:00:00"),
        ])


class FakeSettings:
    def get_stores(self):
        return []


def test_product_list_sorts_newest_formal_product_first(tmp_path):
    service = ProductApplicationService(
        product_repo=FakeProductRepo(),
        settings_facade=FakeSettings(),
        event_bus=None,
        data_root=str(tmp_path),
    )

    products = service.list_products()

    assert [p["skc"] for p in products] == ["NEW", "MID", "OLD"]
    assert products[0]["created_at"] == "2026-05-27T09:30:00"
