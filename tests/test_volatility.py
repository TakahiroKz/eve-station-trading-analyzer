"""D6: volatility.py no está enganchado a ningún endpoint/motor todavía), pero es una función pura sin efectos secundarios."""
import pandas as pd
import pytest

from analytics.volatility import volatility_summary


def test_volatility_cv_is_zero_for_a_constant_price():
    history = pd.DataFrame([
        {"type_id": 34, "date": f"2026-09-{i + 1:02d}", "avg_price": 5.0, "highest": 5.2, "lowest": 4.8}
        for i in range(3)
    ])

    result = volatility_summary(history)

    assert result.iloc[0]["price_std"] == 0
    assert result.iloc[0]["volatility_cv"] == 0


def test_volatility_cv_is_positive_when_price_varies():
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "avg_price": 4.0, "highest": 4.2, "lowest": 3.8},
        {"type_id": 34, "date": "2026-09-02", "avg_price": 6.0, "highest": 6.2, "lowest": 5.8},
    ])

    result = volatility_summary(history)

    assert result.iloc[0]["volatility_cv"] > 0


def test_volatility_cv_is_filled_with_zero_for_a_single_observation():
    # std de una sola muestra es NaN en pandas -- volatility_cv lo rellena con 0
    # en vez de dejarlo como NaN (ver .fillna(0) en volatility.py).
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "avg_price": 5.0, "highest": 5.2, "lowest": 4.8},
    ])

    result = volatility_summary(history)

    assert result.iloc[0]["volatility_cv"] == 0


def test_daily_range_pct_is_the_high_low_spread_over_avg_price():
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "avg_price": 5.0, "highest": 5.5, "lowest": 4.5},
    ])

    result = volatility_summary(history)

    assert result.iloc[0]["daily_range_pct_mean"] == pytest.approx((5.5 - 4.5) / 5.0)


def test_volatility_summary_ranks_the_more_volatile_item_first():
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "avg_price": 5.0, "highest": 5.1, "lowest": 4.9},
        {"type_id": 34, "date": "2026-09-02", "avg_price": 5.0, "highest": 5.1, "lowest": 4.9},
        {"type_id": 35, "date": "2026-09-01", "avg_price": 2.0, "highest": 4.0, "lowest": 1.0},
        {"type_id": 35, "date": "2026-09-02", "avg_price": 8.0, "highest": 10.0, "lowest": 6.0},
    ])

    result = volatility_summary(history)

    assert list(result["type_id"]) == [35, 34]
