"""D6: demand.py no está enganchado a ningún endpoint/motor todavía (código listo
para un ranking de demanda a futuro), pero es una función pura
sin efectos secundarios -- se testea igual que el resto de analytics/."""
import pandas as pd
import pytest

from analytics.demand import demand_summary


def _history_rows(type_id: int, volumes: list[float], order_counts: list[float] | None = None):
    order_counts = order_counts or [1] * len(volumes)
    return [
        {"type_id": type_id, "date": f"2026-09-{i + 1:02d}", "volume": v, "order_count": oc}
        for i, (v, oc) in enumerate(zip(volumes, order_counts))
    ]


def test_demand_summary_on_empty_history_returns_an_empty_dataframe():
    result = demand_summary(pd.DataFrame(columns=["type_id", "date", "volume", "order_count"]))
    assert result.empty


def test_demand_summary_ranks_growing_volume_above_flat_volume():
    rows = (
        _history_rows(34, [10, 20, 30, 40, 50])  # tendencia claramente creciente
        + _history_rows(35, [30, 30, 30, 30, 30])  # mismo nivel medio, sin tendencia
    )
    history = pd.DataFrame(rows)

    result = demand_summary(history)

    assert list(result["type_id"]) == [34, 35]  # ordenado desc por demand_score
    growing = result[result["type_id"] == 34].iloc[0]
    flat = result[result["type_id"] == 35].iloc[0]
    assert growing["volume_trend"] > 0
    # np.polyfit sobre una serie constante no da exactamente 0 por ruido de punto
    # flotante (ej. -3.2e-15) -- se compara con tolerancia, no con ==.
    assert flat["volume_trend"] == pytest.approx(0, abs=1e-9)
    assert growing["demand_score"] > flat["demand_score"]


def test_demand_summary_respects_the_window_days_cutoff():
    # 5 días viejos con volumen altísimo, 3 días recientes con volumen bajo -- con
    # window_days=3 el promedio no debería verse arrastrado por los días viejos.
    old = _history_rows(34, [1000, 1000, 1000, 1000, 1000])
    for i, row in enumerate(old):
        row["date"] = f"2026-08-{i + 1:02d}"
    recent = _history_rows(34, [10, 10, 10])
    for i, row in enumerate(recent):
        row["date"] = f"2026-09-{i + 1:02d}"
    history = pd.DataFrame(old + recent)

    result = demand_summary(history, window_days=3)

    assert result.iloc[0]["volume_mean"] == 10
    assert result.iloc[0]["days_observed"] == 3


def test_demand_summary_computes_a_score_for_a_single_item_without_dividing_by_zero():
    # Un solo ítem: volume_trend normalizado contra sí mismo -- no debería tirar
    # ZeroDivisionError ni dejar NaN en demand_score.
    history = pd.DataFrame(_history_rows(34, [10, 10, 10]))
    result = demand_summary(history)
    assert not result["demand_score"].isna().any()
