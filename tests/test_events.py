from analytics.eve_calculator import EveCalculatorResult
from notifications import events


def _result() -> EveCalculatorResult:
    return EveCalculatorResult(
        item="Tritanium", buy=5.0, sell=6.0, volumen_deseado=100, volumen_diario_real=1000,
        beneficio=0.4, spread_bruto=0.2, precio_min_venta=5.5, roi=0.15,
        evaluacion_spread="🟢 Buen margen", posicion_vs_volumen=0.1, liquidez="Buena",
        recomendacion="Mantener", unidades_sugeridas=100,
    )


def test_dispatch_new_opportunity_calls_notify_new_opportunity(monkeypatch):
    calls = []
    monkeypatch.setattr(events, "notify_new_opportunity", lambda result: calls.append(result))

    result = _result()
    events.dispatch([events.NewOpportunity(result)])

    assert calls == [result]


def test_dispatch_position_changed_calls_notify_position_update(monkeypatch):
    calls = []
    monkeypatch.setattr(
        events, "notify_position_update",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    events.dispatch([events.PositionChanged(
        item_name="Tritanium", side="compra", price=5.0,
        orders_ahead=2, price_gap=0.1, best_price=5.1,
    )])

    assert calls == [(("Tritanium", "compra", 5.0, 2, 0.1, 5.1), {"recovered": False})]


def test_dispatch_order_closed_calls_notify_order_closed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        events, "notify_order_closed",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    events.dispatch([events.OrderClosed(item_name="Tritanium", side="venta", price=5.0, final_state="completada")])

    assert calls == [(("Tritanium", "venta", 5.0, "completada"), {"wallet_balance": None})]


def test_dispatch_order_closed_passes_wallet_balance_through(monkeypatch):
    calls = []
    monkeypatch.setattr(
        events, "notify_order_closed",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    events.dispatch([events.OrderClosed(
        item_name="Tritanium", side="venta", price=5.0, final_state="completada", wallet_balance=1234.5,
    )])

    assert calls == [{"wallet_balance": 1234.5}]


def test_dispatch_order_filled_calls_notify_order_filled(monkeypatch):
    calls = []
    monkeypatch.setattr(
        events, "notify_order_filled",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    events.dispatch([events.OrderFilled(
        item_name="Tritanium", side="compra", price=5.0, filled_units=200, volume_remain=800,
    )])

    assert calls == [(("Tritanium", "compra", 5.0, 200, 800), {"wallet_balance": None})]


def test_dispatch_order_filled_passes_wallet_balance_through(monkeypatch):
    calls = []
    monkeypatch.setattr(
        events, "notify_order_filled",
        lambda *args, **kwargs: calls.append(kwargs),
    )

    events.dispatch([events.OrderFilled(
        item_name="Tritanium", side="venta", price=6.0, filled_units=200, volume_remain=800,
        wallet_balance=9999.0,
    )])

    assert calls == [{"wallet_balance": 9999.0}]


def test_dispatch_processes_events_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(events, "notify_new_opportunity", lambda result: calls.append("opportunity"))
    monkeypatch.setattr(events, "notify_order_closed", lambda *a, **kw: calls.append("closed"))

    events.dispatch([
        events.NewOpportunity(_result()),
        events.OrderClosed(item_name="X", side="venta", price=1.0, final_state="completada"),
    ])

    assert calls == ["opportunity", "closed"]


def test_dispatch_empty_list_does_nothing(monkeypatch):
    monkeypatch.setattr(events, "notify_new_opportunity", lambda *a: (_ for _ in ()).throw(AssertionError))
    events.dispatch([])
