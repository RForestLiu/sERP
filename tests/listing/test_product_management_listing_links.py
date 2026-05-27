from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template(name: str) -> str:
    return (ROOT / "templates" / name).read_text(encoding="utf-8")


def test_legacy_product_management_listing_entries_are_hidden():
    template = read_template("index.html")

    assert 'href="/listing-workbench"' not in template
    assert 'href="/product-maintenance"' not in template
    assert "store-listing-btn" not in template
    assert "data-action=\"listing\"" not in template
    assert "window.open(`/ozon-listing?skc=${skc}&store_id=${storeId}`" not in template
    assert "window.open(`/ozon-product/add?skc=${encodeURIComponent(skc)}&store_id=${encodeURIComponent(storeId)}`" not in template


def test_product_maintenance_listing_entries_are_hidden():
    template = read_template("product_maintenance.html")

    assert 'href="/ozon-product/add"' not in template
    assert 'href="/ozon-listing"' not in template
    assert "store-listing-link" not in template
    assert "listingUrl(store.id)" not in template


def test_latest_ozon_editor_preselects_product_from_query_skc():
    template = read_template("ozon_product_editor.html")

    assert 'skc: query.get("skc") || ""' in template
    assert "selectProduct(pageState.skc);" in template
