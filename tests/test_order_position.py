from analytics.order_position import compute_position


def test_buy_order_first_in_book():
    book = [{"order_id": 1, "price": 100}, {"order_id": 2, "price": 90}]
    pos = compute_position(is_buy_order=True, my_order_id=1, my_price=100, book=book)
    assert pos.orders_ahead == 0
    assert pos.price_gap == 0.0
    assert pos.best_price == 100


def test_buy_order_outbid_by_two():
    book = [
        {"order_id": 1, "price": 100},
        {"order_id": 2, "price": 105},
        {"order_id": 3, "price": 110},
    ]
    pos = compute_position(is_buy_order=True, my_order_id=1, my_price=100, book=book)
    assert pos.orders_ahead == 2
    assert pos.best_price == 110
    assert pos.price_gap == 10.0


def test_sell_order_first_in_book():
    book = [{"order_id": 1, "price": 200}, {"order_id": 2, "price": 210}]
    pos = compute_position(is_buy_order=False, my_order_id=1, my_price=200, book=book)
    assert pos.orders_ahead == 0
    assert pos.price_gap == 0.0
    assert pos.best_price == 200


def test_sell_order_undercut_by_one():
    book = [{"order_id": 1, "price": 200}, {"order_id": 2, "price": 190}]
    pos = compute_position(is_buy_order=False, my_order_id=1, my_price=200, book=book)
    assert pos.orders_ahead == 1
    assert pos.best_price == 190
    assert pos.price_gap == 10.0


def test_alone_in_book():
    book = [{"order_id": 1, "price": 50}]
    pos = compute_position(is_buy_order=False, my_order_id=1, my_price=50, book=book)
    assert pos.orders_ahead == 0
    assert pos.price_gap == 0.0
    assert pos.best_price == 50


def test_tied_price_does_not_count_as_ahead():
    book = [{"order_id": 1, "price": 100}, {"order_id": 2, "price": 100}]
    pos = compute_position(is_buy_order=True, my_order_id=1, my_price=100, book=book)
    assert pos.orders_ahead == 0
    assert pos.price_gap == 0.0


def test_book_price_overrides_stale_my_price():
    """Caso real observado: /characters/{id}/orders/ devolvió 3.95 para una orden que el
    usuario ya había reajustado a 3.93 — el libro público de la región (`book`) ya tenía
    el precio nuevo. compute_position() debe confiar en el libro, no en `my_price`."""
    book = [
        {"order_id": 1, "price": 3.93},  # mi propia orden, YA con el precio nuevo
        {"order_id": 2, "price": 3.93},  # competidor al mismo precio
        {"order_id": 3, "price": 3.94},
    ]
    pos = compute_position(is_buy_order=False, my_order_id=1, my_price=3.95, book=book)
    assert pos.my_price == 3.93
    assert pos.orders_ahead == 0  # nadie por debajo de 3.93 — ya no estoy undercuteado
    assert pos.price_gap == 0.0


def test_my_price_falls_back_when_own_order_not_in_book():
    """Si mi propia orden no aparece en el libro (ej. falló la llamada y se armó un book
    mínimo con solo mi orden — ver scheduler/orders_run.py), se usa my_price tal cual."""
    book = [{"order_id": 2, "price": 100}]
    pos = compute_position(is_buy_order=True, my_order_id=1, my_price=90, book=book)
    assert pos.my_price == 90
    assert pos.orders_ahead == 1
