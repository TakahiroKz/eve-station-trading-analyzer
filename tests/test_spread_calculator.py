from domain.spread_calculator import calculate_spread


def test_spread_gamma_l_example():
    result = calculate_spread(buy_price=698_000, sell_price=997_900)
    assert result.spread_isk == 299_900
    assert round(result.spread_pct, 2) == 42.97


def test_spread_zero_diff():
    result = calculate_spread(buy_price=100, sell_price=100)
    assert result.spread_isk == 0
    assert result.spread_pct == 0
