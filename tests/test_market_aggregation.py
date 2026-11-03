from analytics.market_aggregation import build_orders_by_type


def test_picks_highest_buy_and_lowest_sell():
    orders = [
        {"type_id": 34, "is_buy_order": True, "price": 5.0, "volume_remain": 100},
        {"type_id": 34, "is_buy_order": True, "price": 5.5, "volume_remain": 50},
        {"type_id": 34, "is_buy_order": False, "price": 6.0, "volume_remain": 200},
        {"type_id": 34, "is_buy_order": False, "price": 5.8, "volume_remain": 30},
    ]
    by_type = build_orders_by_type(orders)
    assert by_type[34]["best_buy"] == 5.5
    assert by_type[34]["best_sell"] == 5.8


def test_sums_volume_and_counts_orders_per_side():
    orders = [
        {"type_id": 34, "is_buy_order": True, "price": 5.0, "volume_remain": 100},
        {"type_id": 34, "is_buy_order": True, "price": 5.5, "volume_remain": 50},
        {"type_id": 34, "is_buy_order": False, "price": 6.0, "volume_remain": 200},
    ]
    by_type = build_orders_by_type(orders)
    assert by_type[34]["buy_volume"] == 150
    assert by_type[34]["buy_order_count"] == 2
    assert by_type[34]["sell_volume"] == 200
    assert by_type[34]["sell_order_count"] == 1


def test_separates_by_type_id():
    orders = [
        {"type_id": 34, "is_buy_order": True, "price": 5.0, "volume_remain": 100},
        {"type_id": 35, "is_buy_order": True, "price": 10.0, "volume_remain": 20},
    ]
    by_type = build_orders_by_type(orders)
    assert set(by_type.keys()) == {34, 35}
    assert by_type[35]["best_buy"] == 10.0


def test_empty_orders_returns_empty_dict():
    assert build_orders_by_type([]) == {}


def test_only_buy_side_leaves_sell_fields_at_defaults():
    orders = [{"type_id": 34, "is_buy_order": True, "price": 5.0, "volume_remain": 100}]
    by_type = build_orders_by_type(orders)
    assert by_type[34]["best_sell"] is None
    assert by_type[34]["sell_volume"] == 0
    assert by_type[34]["sell_order_count"] == 0
