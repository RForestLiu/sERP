from src.serp.settings.domain.services import DEFAULT_SETTINGS


def test_default_pricing_formulas_include_minimum_profit_rate():
    formulas = DEFAULT_SETTINGS["pricing_formulas"]

    assert formulas
    for formula in formulas:
        assert formula["defaults"]["min_profit_rate"] == 0.2
