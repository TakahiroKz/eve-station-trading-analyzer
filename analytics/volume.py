"""Ranking por volumen absoluto (unidades y valor ISK) a partir de market_history."""
import pandas as pd


def volume_summary(history: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """history: columnas [type_id, date, avg_price, highest, lowest, volume, order_count].

    Devuelve un DataFrame por type_id con volumen medio diario en unidades y en ISK,
    usando los últimos `window_days` días disponibles por ítem.
    """
    recent = (
        history.sort_values("date")
        .groupby("type_id", group_keys=False)
        .apply(lambda g: g.tail(window_days))
    )
    recent = recent.assign(isk_volume=recent["volume"] * recent["avg_price"])

    summary = recent.groupby("type_id").agg(
        unit_volume_mean=("volume", "mean"),
        isk_volume_mean=("isk_volume", "mean"),
        days_observed=("date", "count"),
    ).reset_index()

    return summary.sort_values("isk_volume_mean", ascending=False)
