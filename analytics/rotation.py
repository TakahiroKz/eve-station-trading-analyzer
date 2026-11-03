"""Rotación: qué tan rápido se mueve el stock de un ítem, a partir de market_history."""
import pandas as pd


def rotation_summary(history: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """rotation_index = volumen medio diario / order_count medio diario.

    Un valor alto indica que cada orden mueve muchas unidades en promedio (alta
    rotación); útil para distinguir ítems con volumen alto pero repartido en pocas
    órdenes grandes (rotación real) de ítems con volumen alto por muchas órdenes
    pequeñas (mercado fragmentado).
    """
    recent = (
        history.sort_values("date")
        .groupby("type_id", group_keys=False)
        .apply(lambda g: g.tail(window_days))
    )

    summary = recent.groupby("type_id").agg(
        volume_mean=("volume", "mean"),
        order_count_mean=("order_count", "mean"),
        days_observed=("date", "count"),
    ).reset_index()

    summary["rotation_index"] = summary["volume_mean"] / summary["order_count_mean"].replace(0, pd.NA)
    return summary.sort_values("rotation_index", ascending=False)
