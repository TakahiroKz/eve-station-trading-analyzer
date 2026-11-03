"""D6: volume.py no está enganchado a ningún endpoint/motor todavía (ver
DEUDA_TECNICA.md), pero es una función pura sin efectos secundarios."""
import pandas as pd

from analytics.volume import volume_summary


def test_volume_summary_computes_unit_and_isk_volume_means():
    history = pd.DataFrame([
        {"type_id": 34, "date": "2026-09-01", "avg_price": 5.0, "volume": 100},
        {"type_id": 34, "date": "2026-09-02", "avg_price": 5.0, "volume": 200},
    ])

    result = volume_summary(history)

    row = result.iloc[0]
    assert row["unit_volume_mean"] == 150
    # isk_volume por día: 100*5=500, 200*5=1000 -> media 750
    assert row["isk_volume_mean"] == 750


def test_volume_summary_ranks_by_isk_volume_not_unit_volume():
    history = pd.DataFrame([
        # Muchas unidades pero baratas.
        {"type_id": 34, "date": "2026-09-01", "avg_price": 1.0, "volume": 10_000},
        # Pocas unidades pero carísimas -> más ISK movido en total.
        {"type_id": 35, "date": "2026-09-01", "avg_price": 100_000.0, "volume": 5},
    ])

    result = volume_summary(history)

    assert list(result["type_id"]) == [35, 34]


def test_volume_summary_respects_the_window_days_cutoff():
    rows = [
        {"type_id": 34, "date": f"2026-08-{i + 1:02d}", "avg_price": 1.0, "volume": 1000}
        for i in range(5)
    ] + [
        {"type_id": 34, "date": f"2026-09-{i + 1:02d}", "avg_price": 1.0, "volume": 10}
        for i in range(2)
    ]
    history = pd.DataFrame(rows)

    result = volume_summary(history, window_days=2)

    assert result.iloc[0]["unit_volume_mean"] == 10
    assert result.iloc[0]["days_observed"] == 2
