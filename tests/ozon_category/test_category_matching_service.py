from src.serp.ozon_category.domain.services import CategoryMatchingService


def test_keyword_score_uses_candidate_argument():
    score = CategoryMatchingService.keyword_score(
        {"name": "Wallet", "cn": "钱包"},
        {"wallet", "phone"},
    )

    assert score == 2


def test_prompt_for_non_leaf_level_requires_best_choice():
    prompt = CategoryMatchingService.build_level_prompt(
        candidates=[
            {"id": 1, "name": "Одежда", "cn": "服装", "is_leaf": False},
            {"id": 2, "name": "Галантерея и аксессуары", "cn": "小百货和配饰", "is_leaf": False},
        ],
        product_title="BOSTANTEN Wristlet Wallets for Women",
        product_category="Clothing, Shoes & Jewelry > Women > Accessories > Wallets",
        product_description="RFID wallet with wrist strap and zipper pockets",
        level_desc="根级品类",
        allow_null=False,
    )

    assert "必须选择最接近的一个候选" in prompt
    assert "不要返回 null" in prompt
    assert "Wallets" in prompt


def test_parse_match_response_null_is_not_parse_error():
    cid, err = CategoryMatchingService.parse_match_response(
        '{"category_id": null, "reason": "too broad"}',
        {"1", "2"},
    )

    assert cid is None
    assert err == ""


def test_category_match_tool_limits_category_id_to_candidates():
    tool = CategoryMatchingService.build_category_match_tool(
        candidates=[{"id": 1}, {"id": 2}],
        allow_null=False,
    )

    fn = tool["function"]
    assert tool["type"] == "function"
    assert fn["name"] == "select_ozon_category"
    assert fn["strict"] is True
    assert fn["parameters"]["properties"]["category_id"]["type"] == "string"
    assert fn["parameters"]["properties"]["category_id"]["enum"] == ["1", "2"]
    assert fn["parameters"]["additionalProperties"] is False


def test_parse_match_response_reads_tool_call_arguments():
    response = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "function": {
                        "name": "select_ozon_category",
                        "arguments": '{"category_id": "2", "reason": "wallet accessories", "confidence": 0.82}',
                    }
                }]
            }
        }]
    }

    text = CategoryMatchingService.extract_match_response_text(response)
    cid, err = CategoryMatchingService.parse_match_response(text, {"1", "2"})

    assert cid == 2
    assert err == ""


def test_parse_match_response_reads_none_sentinel():
    cid, err = CategoryMatchingService.parse_match_response(
        '{"category_id": "__NONE__", "reason": "no leaf fits", "confidence": 0.3}',
        {"1", "2"},
    )

    assert cid is None
    assert err == ""
