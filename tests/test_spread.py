"""D6: spread.py no está enganchado a ningún endpoint/motor todavía), pero es una función pura sin efectos secundarios. La fórmula de
spread_bruto en sí ya tiene su propio test en test_eve_calculator.py -- acá se
verifica el armado del resumen (filtrado, "última foto por ítem", orden)."""
import pandas as pd
import pytest

from analytics.spread import spread_summary


def test_spread_summary_uses_only_the_latest_snapshot_per_item():
    snapshot = pd.DataFrame([
        {"type_id": 34, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 4.0, "best_sell": 4.1},
        {"type_id": 34, "captured_at": "2026-09-02T00:00:00Z", "best_buy": 4.0, "best_sell": 5.0},
    ])

    result = spread_summary(snapshot)

    assert len(result) == 1
    assert result.iloc[0]["captured_at"] == "2026-09-02T00:00:00Z"
    assert result.iloc[0]["spread_bruto"] == pytest.approx(5.0 / 4.0 - 1)


def test_spread_summary_drops_rows_missing_best_buy_or_best_sell():
    snapshot = pd.DataFrame([
        {"type_id": 34, "captured_at": "2026-09-01T00:00:00Z", "best_buy": None, "best_sell": 4.1},
        {"type_id": 35, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 4.0, "best_sell": None},
        {"type_id": 36, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 4.0, "best_sell": 4.5},
    ])

    result = spread_summary(snapshot)

    assert list(result["type_id"]) == [36]


def test_spread_summary_drops_rows_with_a_non_positive_best_buy():
    snapshot = pd.DataFrame([
        {"type_id": 34, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 0, "best_sell": 4.1},
        {"type_id": 35, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 4.0, "best_sell": 4.5},
    ])

    result = spread_summary(snapshot)

    assert list(result["type_id"]) == [35]


def test_spread_summary_sorts_by_spread_descending():
    snapshot = pd.DataFrame([
        {"type_id": 34, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 10.0, "best_sell": 11.0},  # 10%
        {"type_id": 35, "captured_at": "2026-09-01T00:00:00Z", "best_buy": 10.0, "best_sell": 15.0},  # 50%
    ])

    result = spread_summary(snapshot)

    assert list(result["type_id"]) == [35, 34]
