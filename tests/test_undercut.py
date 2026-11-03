from analytics.undercut import is_order_undercut


def test_buy_order_undercut_when_someone_bids_higher():
    assert is_order_undercut(is_buy_order=True, my_price=100, region_best_buy=105, region_best_sell=130) is True


def test_buy_order_not_undercut_when_i_am_the_best_bid():
    assert is_order_undercut(is_buy_order=True, my_price=100, region_best_buy=100, region_best_sell=130) is False


def test_sell_order_undercut_when_someone_sells_cheaper():
    assert is_order_undercut(is_buy_order=False, my_price=130, region_best_buy=100, region_best_sell=120) is True


def test_sell_order_not_undercut_when_i_am_the_best_ask():
    assert is_order_undercut(is_buy_order=False, my_price=130, region_best_buy=100, region_best_sell=130) is False


def test_sell_order_zero_region_price_is_not_undercut():
    """0 es 'sin dato' (item nunca clasificado), no un precio real más barato."""
    assert is_order_undercut(is_buy_order=False, my_price=130, region_best_buy=0, region_best_sell=0) is False


def test_missing_region_price_is_not_undercut():
    assert is_order_undercut(is_buy_order=True, my_price=100, region_best_buy=None, region_best_sell=None) is False
