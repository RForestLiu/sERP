from src.serp.ozon_category.domain.services import CategoryMatchingService


def test_keyword_score_uses_candidate_argument():
    score = CategoryMatchingService.keyword_score(
        {"name": "Wallet", "cn": "钱包"},
        {"wallet", "phone"},
    )

    assert score == 2
