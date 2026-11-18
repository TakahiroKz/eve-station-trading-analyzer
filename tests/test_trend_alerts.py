import pandas as pd

from analytics.trend_alerts import COOLDOWN_DAYS, TrendAlertState, advance
from notifications import events
from notifications.events import TrendChanged, dispatch
from notifications.telegram_bot import notify_trend_change
from scheduler.run import screen_opportunities
from storage.db import get_connection, init_db


def _run(readings):
    """Aplica una lista de (etiqueta, fecha) y devuelve las fechas en las que se avisó."""
    state, alerted = None, []
    for label, day in readings:
        state, alert = advance(state, label, day)
        if alert:
            alerted.append(day)
    return alerted


def test_first_reading_never_alerts_second_consecutive_one_does():
    assert _run([("up", "2026-11-10")]) == []
    assert _run([("up", "2026-11-10"), ("up", "2026-11-11")]) == ["2026-11-11"]


def test_same_day_readings_do_not_count_twice():
    assert _run([("up", "2026-11-10"), ("up", "2026-11-10"), ("up", "2026-11-10")]) == []


def test_flat_and_low_liquidity_never_alert():
    assert _run([("flat", "2026-11-10"), ("flat", "2026-11-11"), ("lowliq", "2026-11-12"),
                 ("nodata", "2026-11-13")]) == []


def test_a_break_in_the_signal_restarts_the_confirmation():
    assert _run([("up", "2026-11-10"), ("flat", "2026-11-11"), ("up", "2026-11-12")]) == []


def test_one_alert_per_streak():
    readings = [("up", f"2026-11-{d:02d}") for d in range(10, 16)]
    assert _run(readings) == ["2026-11-11"]


def test_a_new_streak_waits_for_the_cooldown():
    readings = [("up", "2026-11-10"), ("up", "2026-11-11"),       # aviso el 11
                ("flat", "2026-11-12"),
                ("up", "2026-11-13"), ("up", "2026-11-14"),       # racha nueva, pero solo 3 días después del aviso
                ("up", "2026-11-15")]
    alerted = _run(readings)
    assert alerted[0] == "2026-11-11"
    assert all((pd.Timestamp(d) - pd.Timestamp("2026-11-11")).days >= COOLDOWN_DAYS for d in alerted[1:])


def test_a_large_gap_between_readings_restarts_the_streak():
    assert _run([("up", "2026-11-01"), ("up", "2026-11-09")]) == []


def test_direction_change_is_a_new_signal():
    readings = [("up", "2026-11-10"), ("up", "2026-11-11"), ("down", "2026-11-12"), ("down", "2026-11-13"),
                ("down", "2026-11-14"), ("down", "2026-11-15")]
    alerted = _run(readings)
    assert alerted[0] == "2026-11-11" and len(alerted) == 2 and alerted[1] >= "2026-11-14"


def test_state_dataclass_roundtrip():
    state, _ = advance(None, "up", "2026-11-10")
    assert TrendAlertState(**state.__dict__) == state


def test_dispatch_trend_changed_calls_notify_trend_change(monkeypatch):
    calls = []
    monkeypatch.setattr(events, "notify_trend_change", lambda *a: calls.append(a))
    monkeypatch.setattr(events, "_submit", lambda fn, *a, **k: fn(*a, **k))
    dispatch([TrendChanged("Tritanium", "Jita", "up", 0.12, 0.05, 30.0, ("venta",))])
    assert calls == [("Tritanium", "Jita", "up", 0.12, 0.05, 30.0, ("venta",))]


def test_trend_message_text(monkeypatch):
    sent = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr("notifications.telegram_bot.deliver", lambda text: sent.append(text) or True)
    assert notify_trend_change("Tritanium", "Jita", "down", -0.081, 0.06, 28.0, ("compra", "venta"))
    text = sent[0]
    assert "a la baja" in text and "Tritanium (Jita)" in text and "-8.1%" in text and "±6.0%" in text
    assert "orden de compra y orden de venta" in text and "no una predicción" in text


def _seed_market(path, last_index):
    c = get_connection(path)
    c.execute("INSERT OR IGNORE INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    c.execute("DELETE FROM market_history")
    days = pd.date_range("2026-11-01", periods=16)
    for i, day in enumerate(days[: last_index + 1]):
        price = 100.0 if i < 9 else 130.0
        c.execute(
            "INSERT INTO market_history (market_id, type_id, date, avg_price, highest, lowest, volume, order_count) "
            "VALUES ('jita', 34, ?, ?, ?, ?, 1000, 30)", (day.strftime("%Y-%m-%d"), price, price, price))
    c.commit()
    c.close()


def test_screening_alerts_once_for_an_item_with_an_active_order_after_two_daily_readings(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    init_db(path)
    c = get_connection(path)
    c.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    c.execute(
        "INSERT INTO market_snapshot (market_id, type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) VALUES ('jita', 34, datetime('now'), 120, 140, 1000, 1000, 3, 3)")
    c.execute(
        "INSERT INTO character_order (order_id, type_id, region_id, is_buy_order, price, volume_remain, "
        "volume_total, issued, first_seen_at, last_seen_at) VALUES (1, 34, 10000002, 0, 140, 5, 10, "
        "'2026-11-10T00:00:00', '2026-11-10T00:00:00', '2026-11-10T00:00:00')")
    c.commit()
    c.close()
    batches = []
    monkeypatch.setattr("scheduler.run.get_current_wallet_balance", lambda: 5_000_000.0)
    monkeypatch.setattr("scheduler.run.dispatch", lambda evs: batches.append(list(evs)))

    def alerts():
        return [e for batch in batches for e in batch if isinstance(e, TrendChanged)]

    _seed_market(path, last_index=14)
    screen_opportunities(path, str(tmp_path / "r.xlsx"))
    assert alerts() == []  # primera lectura: todavía no está confirmada

    screen_opportunities(path, str(tmp_path / "r.xlsx"))
    assert alerts() == []  # misma fecha de histórico: no cuenta como otra lectura

    _seed_market(path, last_index=15)
    screen_opportunities(path, str(tmp_path / "r.xlsx"))
    found = alerts()
    assert len(found) == 1
    assert found[0].item_name == "Tritanium" and found[0].label == "up" and found[0].sides == ("venta",)
    assert found[0].market_name == "Jita" and found[0].change > 0.2

    screen_opportunities(path, str(tmp_path / "r.xlsx"))
    assert len(alerts()) == 1  # no se repite


def test_screening_does_not_alert_without_an_active_order(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    init_db(path)
    c = get_connection(path)
    c.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    c.execute(
        "INSERT INTO market_snapshot (market_id, type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) VALUES ('jita', 34, datetime('now'), 120, 140, 1000, 1000, 3, 3)")
    c.commit()
    c.close()
    batches = []
    monkeypatch.setattr("scheduler.run.get_current_wallet_balance", lambda: 5_000_000.0)
    monkeypatch.setattr("scheduler.run.dispatch", lambda evs: batches.append(list(evs)))
    for last in (14, 15):
        _seed_market(path, last_index=last)
        screen_opportunities(path, str(tmp_path / "r.xlsx"))
    assert [e for b in batches for e in b if isinstance(e, TrendChanged)] == []
