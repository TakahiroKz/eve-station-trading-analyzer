from analytics.sanity import SanityConfig, is_price_sane


def test_real_trade_is_sane():
    assert is_price_sane(best_buy=100, best_sell=130, reference_price=115) is True


def test_custom_config_changes_the_ratio_bounds():
    """Con el default (0.2), best_buy=30 vs reference=115 (26%) es sano; con un config
    más estricto (0.3 = 30% mínimo) el mismo caso pasa a ser una orden basura."""
    assert is_price_sane(best_buy=30, best_sell=130, reference_price=115) is True
    strict = SanityConfig(sanity_min_ratio=0.3, sanity_max_ratio=5.0)
    assert is_price_sane(best_buy=30, best_sell=130, reference_price=115, config=strict) is False


def test_troll_buy_order_is_rejected():
    # Caso real observado: buy=0.1 vs histórico ~250,000
    assert is_price_sane(best_buy=0.1, best_sell=777_800, reference_price=250_000) is False


def test_troll_sell_order_is_rejected():
    assert is_price_sane(best_buy=100, best_sell=999_999, reference_price=115) is False


def test_no_reference_price_is_rejected():
    assert is_price_sane(best_buy=100, best_sell=130, reference_price=0) is False
