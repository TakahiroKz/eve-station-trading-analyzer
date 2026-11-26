"""analytics/activity_window.py: la actividad se mide en días naturales, con 0 en los días sin operaciones."""
from datetime import date, timedelta

import pandas as pd
import pytest

from analytics.activity_window import activity_windows

ANCHOR = date(2026, 11, 25)


def hist(rows):
    return pd.DataFrame([{"type_id": t, "date": (ANCHOR - timedelta(days=d)).isoformat(), "volume": v, "order_count": o}
                         for t, d, v, o in rows])


def test_an_item_trading_every_day_keeps_its_daily_average():
    w = activity_windows(hist([(1, d, 100, 5) for d in range(30)]), ANCHOR)
    assert w.loc[1].tolist() == [100.0, 100.0, 5.0]


def test_days_without_trades_count_as_zero():
    # 7 días con operaciones en 31: con "las últimas 7 filas" salía 4 ops/día y 1000 u/día
    w = activity_windows(hist([(1, d, 1000, 4) for d in (0, 5, 10, 15, 20, 25, 30)]), ANCHOR)
    assert w.loc[1, "avg_daily_order_count_7d"] == pytest.approx(8 / 7)
    assert w.loc[1, "avg_daily_volume_7d"] == pytest.approx(2000 / 7)
    assert w.loc[1, "volumen_diario_real"] == pytest.approx(6000 / 30)   # el día 30 queda fuera de los 30 días


def test_the_window_ends_at_the_anchor_not_today_and_includes_it():
    rows = [(1, 0, 70, 7), (1, 6, 70, 7), (1, 7, 700, 70), (1, 29, 30, 3), (1, 30, 9999, 99)]
    w = activity_windows(hist(rows), ANCHOR.isoformat())
    assert w.loc[1, "avg_daily_volume_7d"] == pytest.approx(140 / 7)          # días 0 y 6 dentro; el 7 fuera
    assert w.loc[1, "avg_daily_order_count_7d"] == pytest.approx(14 / 7)
    assert w.loc[1, "volumen_diario_real"] == pytest.approx((70 + 70 + 700 + 30) / 30)


def test_an_item_with_only_old_trades_has_zero_activity_but_is_listed():
    w = activity_windows(hist([(1, 0, 10, 1), (2, 45, 500, 9)]), ANCHOR)
    assert w.loc[2].tolist() == [0.0, 0.0, 0.0]
    assert list(w.index) == [1, 2] and w.index.name == "type_id"


def test_empty_history_or_no_anchor_gives_an_empty_frame():
    assert activity_windows(pd.DataFrame(columns=["type_id", "date", "volume", "order_count"]), ANCHOR).empty
    assert activity_windows(hist([(1, 0, 10, 1)]), None).empty


def test_rows_after_the_anchor_do_not_count():
    w = activity_windows(hist([(1, 0, 70, 7), (1, -1, 7000, 700)]), ANCHOR)   # un día posterior al ancla
    assert w.loc[1].tolist() == [pytest.approx(70 / 30), 10.0, 1.0]


def test_an_item_newer_than_the_window_is_divided_by_the_days_it_has_existed():
    rows = [(1, d, 100, 10) for d in range(15)] + [(2, d, 100, 10) for d in (0, 5, 10)]
    first = pd.Series({1: (ANCHOR - timedelta(days=14)).isoformat(), 2: "2025-01-01"})
    w = activity_windows(hist(rows), ANCHOR, first)
    assert w.loc[1].tolist() == [100.0, 100.0, 10.0]                    # 15 días de vida: ni 30 ni 7 lo diluyen
    assert w.loc[2, "volumen_diario_real"] == pytest.approx(300 / 30)    # ítem viejo con huecos: sí cuentan los ceros
    assert w.loc[2, "avg_daily_order_count_7d"] == pytest.approx(20 / 7)


def test_an_item_born_yesterday_is_divided_by_its_two_days():
    first = pd.Series({1: (ANCHOR - timedelta(days=1)).isoformat()})
    w = activity_windows(hist([(1, 0, 50, 4), (1, 1, 30, 2)]), ANCHOR, first)
    assert w.loc[1].tolist() == [40.0, 40.0, 3.0]
