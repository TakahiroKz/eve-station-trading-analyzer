import pytest

from analytics.eve_calculator import EveCalculatorResult
from notifications import events


def _result() -> EveCalculatorResult:
    return EveCalculatorResult(
        item="Tritanium", buy=5.0, sell=6.0, volumen_deseado=100, volumen_diario_real=1000,
        beneficio=0.4, spread_bruto=0.2, precio_min_venta=5.5, roi=0.15,
        evaluacion_spread="🟢 Buen margen", posicion_vs_volumen=0.1, liquidez="Buena",
        recomendacion="Mantener", unidades_sugeridas=100,
    )


def test_dispatch_new_opportunity_calls_notify_new_opportunity_when_enabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_NOTIFY_OPPORTUNITIES", "1")
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
    monkeypatch.setenv("TELEGRAM_NOTIFY_OPPORTUNITIES", "1")
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


@pytest.fixture(autouse=True)
def _run_sends_inline(monkeypatch):
    """Los tests de arriba comprueban qué función de notify_* se llama; se ejecutan en el momento
    (el comportamiento asíncrono real tiene sus propios tests más abajo)."""
    monkeypatch.setattr(events, "_submit", lambda fn, *args, **kwargs: fn(*args, **kwargs))


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "notify.db"))


def test_dispatch_returns_immediately_and_sends_in_parallel_in_the_background(monkeypatch):
    import threading
    import time

    started = []
    release = threading.Event()

    def slow_send(*args, **kwargs):
        started.append(time.monotonic())
        release.wait(2)
        return True

    monkeypatch.setattr(events, "_submit", events._real_submit)
    monkeypatch.setattr(events, "notify_order_closed", slow_send)

    begin = time.monotonic()
    events.dispatch([
        events.OrderClosed(item_name=f"Item{n}", side="venta", price=1.0, final_state="completada")
        for n in range(4)
    ])
    elapsed = time.monotonic() - begin

    assert elapsed < 0.2  # dispatch no espera a los envíos
    time.sleep(0.3)
    assert len(started) == 4  # los cuatro empezaron a la vez (en paralelo)
    release.set()
    events.flush_notifications(timeout=3)


def test_flush_waits_for_pending_sends_up_to_the_timeout_and_then_returns(monkeypatch):
    import threading
    import time

    done = []
    release = threading.Event()

    def slow_send(*args, **kwargs):
        release.wait(5)
        done.append(1)
        return True

    monkeypatch.setattr(events, "_submit", events._real_submit)
    monkeypatch.setattr(events, "notify_order_closed", slow_send)
    events.dispatch([events.OrderClosed(item_name="X", side="venta", price=1.0, final_state="completada")])

    begin = time.monotonic()
    events.flush_notifications(timeout=0.3)
    elapsed = time.monotonic() - begin

    assert 0.25 <= elapsed < 1.5  # esperó el límite y no más
    assert done == []  # el envío sigue en segundo plano
    release.set()
    time.sleep(0.3)
    assert done == [1]


def test_flush_with_nothing_pending_returns_at_once():
    import time

    begin = time.monotonic()
    events.flush_notifications(timeout=5)
    assert time.monotonic() - begin < 0.5


def test_a_failing_send_never_propagates_to_the_engine(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("telegram caído")

    monkeypatch.setattr(events, "_submit", events._real_submit)
    monkeypatch.setattr(events, "notify_order_closed", boom)

    events.dispatch([events.OrderClosed(item_name="X", side="venta", price=1.0, final_state="completada")])
    events.flush_notifications(timeout=2)  # no debe lanzar


def test_opportunity_notifications_are_suspended_by_default(monkeypatch):
    monkeypatch.delenv("TELEGRAM_NOTIFY_OPPORTUNITIES", raising=False)
    calls = []
    monkeypatch.setattr(events, "notify_new_opportunity", lambda result: calls.append(result))

    events.dispatch([events.NewOpportunity(_result())])

    assert calls == []
    assert events.opportunity_notifications_enabled() is False


def test_the_opportunity_switch_only_accepts_an_explicit_one(monkeypatch):
    for value, expected in (("1", True), (" 1 ", True), ("0", False), ("", False), ("true", False)):
        monkeypatch.setenv("TELEGRAM_NOTIFY_OPPORTUNITIES", value)
        assert events.opportunity_notifications_enabled() is expected


def test_order_and_position_notifications_still_go_out_with_opportunities_suspended(monkeypatch):
    monkeypatch.delenv("TELEGRAM_NOTIFY_OPPORTUNITIES", raising=False)
    sent = []
    monkeypatch.setattr(events, "notify_new_opportunity", lambda result: sent.append("oportunidad"))
    monkeypatch.setattr(events, "notify_position_update", lambda *a, **k: sent.append("posicion"))
    monkeypatch.setattr(events, "notify_order_closed", lambda *a, **k: sent.append("cierre"))
    monkeypatch.setattr(events, "notify_order_filled", lambda *a, **k: sent.append("ejecucion"))

    events.dispatch([
        events.NewOpportunity(_result()),
        events.PositionChanged(item_name="X", side="compra", price=1.0, orders_ahead=1, price_gap=0.1, best_price=1.1),
        events.OrderClosed(item_name="X", side="venta", price=1.0, final_state="completada"),
        events.OrderFilled(item_name="X", side="compra", price=1.0, filled_units=1, volume_remain=2),
    ])

    assert sent == ["posicion", "cierre", "ejecucion"]
