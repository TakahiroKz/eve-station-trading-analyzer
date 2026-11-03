"""D6: rotation.py no está enganchado a ningún endpoint/motor todavía (ver
DEUDA_TECNICA.md), pero es una función pura sin efectos secundarios."""
import pandas as pd

from analytics.rotation import rotation_summary


def test_rotation_index_is_volume_mean_over_order_count_mean():
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "volume": 100, "order_count": 10},
        {"type_id": 34, "date": "2026-09-02", "volume": 100, "order_count": 10},
    ])

    result = rotation_summary(history)

    assert result.iloc[0]["type_id"] == 34
    assert result.iloc[0]["rotation_index"] == 10.0


def test_rotation_summary_ranks_higher_rotation_first():
    history = pd.DataFrame([
        # Mismo volumen medio, pero repartido en muchas más órdenes -> rotación baja.
        {"type_id": 34, "date": "2026-09-01", "volume": 1000, "order_count": 100},
        # Pocas órdenes grandes -> rotación alta.
        {"type_id": 35, "date": "2026-09-01", "volume": 1000, "order_count": 5},
    ])

    result = rotation_summary(history)

    assert list(result["type_id"]) == [35, 34]


def test_rotation_index_is_nan_when_order_count_mean_is_zero_instead_of_dividing_by_zero():
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "volume": 500, "order_count": 0},
    ])

    result = rotation_summary(history)

    assert pd.isna(result.iloc[0]["rotation_index"])


def test_rotation_summary_respects_the_window_days_cutoff():
    rows = [
        {"type_id": 34, "date": f"2026-08-{i + 1:02d}", "volume": 1000, "order_count": 1}
        for i in range(5)
    ] + [
        {"type_id": 34, "date": f"2026-09-{i + 1:02d}", "volume": 10, "order_count": 1}
        for i in range(2)
    ]
    history = pd.DataFrame(rows)

    result = rotation_summary(history, window_days=2)

    assert result.iloc[0]["volume_mean"] == 10
    assert result.iloc[0]["days_observed"] == 2
