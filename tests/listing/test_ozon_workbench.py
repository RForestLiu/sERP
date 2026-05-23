from src.serp.listing.domain.ozon_workbench import (
    WALLET_CATEGORY_ID,
    WALLET_TYPE_ID,
    build_wallet_rich_content,
    collect_ozon_skus,
    match_wallet_category,
    resolve_wallet_brand,
    validate_workbench_payload,
)


def test_match_wallet_category_for_wallet_title():
    result = match_wallet_category({
        "skc": "WALLET-0006",
        "title": "Bostanten wristlet wallet black",
        "category": "wallets",
    })

    assert result["matched"] is True
    assert result["description_category_id"] == WALLET_CATEGORY_ID
    assert result["type_id"] == WALLET_TYPE_ID
    assert result["source"] == "wallet_rule"


def test_build_wallet_rich_content_uses_ozon_template():
    rich = build_wallet_rich_content([
        "https://example.com/1.png",
        "https://example.com/2.png",
        "https://example.com/3.png",
    ])

    assert rich["version"] == 0.3
    assert rich["content"][0]["widgetName"] == "raShowcase"
    assert rich["content"][0]["type"] == "billboard"
    assert len(rich["content"][0]["blocks"]) == 3


def test_collect_ozon_skus_from_info_list_shape():
    result = {
        "items": [{
            "sku": 4408894048,
            "sources": [{"sku": 4408894048}],
        }]
    }

    assert collect_ozon_skus(result) == [4408894048]


def test_validate_blocks_untrusted_brand():
    payload = {
        "category_id": WALLET_CATEGORY_ID,
        "type_id": WALLET_TYPE_ID,
        "name": "Wallet Bostanten WALLET-0006 black",
        "description": "x" * 500,
        "price": "99.00",
        "offer_id": "WALLET-0006-BLACK",
        "images": [{"url": "https://example.com/1.png"}] * 5,
        "attributes": [{
            "attribute_id": 85,
            "value": "Collected Shop",
            "dictionary_value_id": 123,
            "source": "scraped_shop",
        }],
        "skus": [{"name": "WALLET-0006-BLACK", "price": "99.00", "stock": "100"}],
    }

    report = validate_workbench_payload(payload)

    assert report["can_submit"] is False
    assert any("品牌" in issue or "鍝佺墝" in issue for issue in report["issues"])


def test_resolve_wallet_brand_normalizes_store_name():
    result = resolve_wallet_brand({"brand": "BOSTANTEN Store"}, {})

    assert result == {
        "value": "Bostanten",
        "dictionary_value_id": 971068372,
        "source": "known_brand",
    }


def test_resolve_wallet_brand_marks_unknown_product_brand_untrusted():
    result = resolve_wallet_brand({"brand": "Collected Shop"}, {})

    assert result == {
        "value": "Collected Shop",
        "dictionary_value_id": None,
        "source": "scraped_shop",
    }
