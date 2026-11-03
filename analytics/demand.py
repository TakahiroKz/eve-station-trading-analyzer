"""Demanda: crecimiento sostenido de volumen y número de órdenes en market_history."""
import numpy as np
import pandas as pd


def _slope(series: pd.Series) -> float:
    """Pendiente de una regresión lineal simple sobre el índice temporal (0..n-1)."""
    if len(series) < 2 or series.isna().all():
        return 0.0
    y = series.fillna(0).to_numpy()
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0])


def demand_summary(history: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """demand_score combina el nivel de volumen reciente con su tendencia (pendiente).

    Ítems con volumen medio alto Y pendiente positiva se consideran de alta demanda.
    """
    if history.empty:
        return pd.DataFrame(columns=[
            "type_id", "volume_mean", "volume_trend", "order_count_trend",
            "days_observed", "demand_score",
        ])

    recent = (
        history.sort_values("date")
        .groupby("type_id", group_keys=False)
        .apply(lambda g: g.tail(window_days))
    )

    rows = []
    for type_id, group in recent.groupby("type_id"):
        group = group.sort_values("date")
        rows.append({
            "type_id": type_id,
            "volume_mean": group["volume"].mean(),
            "volume_trend": _slope(group["volume"]),
            "order_count_trend": _slope(group["order_count"]),
            "days_observed": len(group),
        })

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    vol_norm = summary["volume_mean"] / summary["volume_mean"].max()
    trend_norm = summary["volume_trend"] / summary["volume_trend"].abs().max() if summary["volume_trend"].abs().max() else 0
    summary["demand_score"] = (0.7 * vol_norm.fillna(0)) + (0.3 * pd.Series(trend_norm).fillna(0))
    return summary.sort_values("demand_score", ascending=False)
