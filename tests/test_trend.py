import sqlite3

import pandas as pd

from analytics.trend import TrendConfig, compute_price_trends
from storage.db import get_app_settings_dict, init_db, upsert_item_status


def _history(rows):
    return pd.DataFrame(rows, columns=["type_id", "date", "avg_price", "volume", "order_count"])


def _series(type_id, prices, orders=20, volume=100, end="2026-11-14"):
    days = pd.date_range(end=end, periods=len(prices))
    return [(type_id, d.strftime("%Y-%m-%d"), p, volume, orders) for d, p in zip(days, prices)]


def test_rising_price_is_up():
    prices = [100.0] * 7 + [120.0] * 7
    out = compute_price_trends(_history(_series(1, prices)))
    assert out.loc[1, "price_trend_label"] == "up"
    assert abs(out.loc[1, "price_trend"] - 0.20) < 1e-9


def test_falling_price_is_down():
    out = compute_price_trends(_history(_series(1, [100.0] * 7 + [80.0] * 7)))
    assert out.loc[1, "price_trend_label"] == "down"
    assert out.loc[1, "price_trend"] < 0


def test_small_move_is_flat_with_floor_threshold():
    out = compute_price_trends(_history(_series(1, [100.0] * 7 + [102.0] * 7)))
    assert out.loc[1, "price_trend_label"] == "flat"
    assert out.loc[1, "price_trend_threshold"] >= 0.05


def test_noisy_item_needs_a_bigger_move():
    noisy = [100, 140, 70, 130, 80, 150, 90, 120, 60, 140, 75, 135, 85, 145]
    out = compute_price_trends(_history(_series(1, [float(p) for p in noisy])))
    assert out.loc[1, "price_trend_threshold"] > 0.15


def test_low_liquidity_label():
    out = compute_price_trends(_history(_series(1, [100.0] * 7 + [130.0] * 7, orders=1)),
                               TrendConfig(trend_min_ops_per_day=5))
    assert out.loc[1, "price_trend_label"] == "lowliq"


def test_not_enough_history_is_nodata_without_numbers():
    out = compute_price_trends(_history(_series(1, [100.0, 110.0, 120.0])))
    assert out.loc[1, "price_trend_label"] == "nodata"
    assert pd.isna(out.loc[1, "price_trend"]) and pd.isna(out.loc[1, "price_trend_threshold"])


def test_item_with_stale_history_is_nodata_when_market_is_current():
    rows = _series(1, [100.0] * 14) + _series(2, [100.0] * 14, end="2026-11-01")
    out = compute_price_trends(_history(rows))
    assert out.loc[1, "price_trend_label"] != "nodata"
    assert out.loc[2, "price_trend_label"] == "nodata"


def test_empty_history():
    assert compute_price_trends(_history([])).empty


def test_vwap_weights_by_volume():
    # La semana reciente tiene un día barato de poco volumen: el VWAP casi no se mueve.
    prices = [100.0] * 7 + [100.0] * 6 + [50.0]
    rows = []
    for i, (t, d, p, v, o) in enumerate(_series(1, prices)):
        rows.append((t, d, p, 1 if i == 13 else 1000, o))
    out = compute_price_trends(_history(rows))
    assert abs(out.loc[1, "price_trend"]) < 0.01


def test_settings_are_seeded_and_trend_columns_persist(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    settings = get_app_settings_dict(conn)
    assert settings["trend_noise_multiplier"] == 1.5
    assert settings["trend_min_change_pct"] == 0.05
    assert settings["trend_min_ops_per_day"] == 5.0
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    row = {
        "type_id": 34, "status": "POTENCIAL", "reason": "ok", "spread_bruto": 0.1,
        "evaluacion_spread": "x", "liquidez": "y", "roi": 0.2, "best_buy": 1, "best_sell": 2,
        "volumen_diario_real": 1, "buy_order_count": 1, "sell_order_count": 1,
        "avg_daily_volume_7d": 1, "avg_daily_order_count_7d": 1, "last_evaluated_at": "2026-11-17T00:00:00",
        "price_trend": 0.08, "price_trend_label": "up", "price_trend_threshold": 0.05,
    }
    upsert_item_status(conn, row)
    got = conn.execute("SELECT price_trend, price_trend_label, price_trend_threshold FROM item_status").fetchone()
    assert tuple(got) == (0.08, "up", 0.05)
    del row["price_trend"], row["price_trend_label"], row["price_trend_threshold"]
    upsert_item_status(conn, row)
    got = conn.execute("SELECT price_trend, price_trend_label, price_trend_threshold FROM item_status").fetchone()
    assert tuple(got) == (None, "nodata", None)
