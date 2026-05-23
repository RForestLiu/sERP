from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_template(name: str) -> str:
    return (ROOT / "templates" / name).read_text(encoding="utf-8")


def test_legacy_product_management_opens_latest_ozon_editor_with_product_context():
    template = read_template("index.html")

    assert "window.open(`/ozon-product/add?skc=${encodeURIComponent(skc)}&store_id=${encodeURIComponent(storeId)}`" in template
    assert "window.open(`/ozon-listing?skc=${skc}&store_id=${storeId}`" not in template


def test_product_maintenance_detail_links_to_latest_ozon_editor_with_selected_product():
    template = read_template("product_maintenance.html")

    assert "listingUrl(store.id)" in template
    assert "/ozon-product/add?skc=" in template
    assert "const skc = state.selectedProduct ? state.selectedProduct.skc : state.selectedSku;" in template
    assert "encodeURIComponent(skc || '')" in template
    assert "encodeURIComponent(storeId || '')" in template


def test_latest_ozon_editor_preselects_product_from_query_skc():
    template = read_template("ozon_product_editor.html")

    assert 'skc: query.get("skc") || ""' in template
    assert "selectProduct(pageState.skc);" in template
