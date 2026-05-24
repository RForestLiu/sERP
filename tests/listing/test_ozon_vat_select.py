from pathlib import Path

from src.serp.listing.application.commands import ListingApplicationService


ROOT = Path(__file__).resolve().parents[2]


def read_template() -> str:
    return (ROOT / "templates" / "ozon_product_editor.html").read_text(encoding="utf-8")


def test_ozon_editor_vat_is_dictionary_select_and_payload_field():
    template = read_template()

    assert 'id="vat-select"' in template
    assert '<option value="0"' in template
    assert '<option value="0.1"' in template
    assert '<option value="0.2"' in template
    assert "function collectVatValue()" in template
    assert "vat: collectVatValue()" in template


def test_ozon_item_builder_uses_selected_vat():
    items = ListingApplicationService._build_ozon_items(
        skus=[],
        name="Wallet",
        price="99",
        offer_id="WALLET-1",
        barcode="",
        category_id=17027904,
        type_id=93338,
        description="",
        ozon_attrs=[],
        base_image_urls=[],
        base_video_urls=[],
        images=[],
        vat="0.2",
    )

    assert items[0]["vat"] == "0.2"
