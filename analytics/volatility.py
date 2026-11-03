"""Volatilidad de precios a partir de market_history."""
import pandas as pd


def volatility_summary(history: pd.DataFrame, window_days: int = 30) -> pd.DataFrame:
    """Coeficiente de variación (std/mean) del precio medio diario por type_id, y el
    rango relativo (highest-lowest)/avg_price promedio como medida complementaria.
    """
    recent = (
        history.sort_values("date")
        .groupby("type_id", group_keys=False)
        .apply(lambda g: g.tail(window_days))
    )
    recent = recent.assign(daily_range_pct=(recent["highest"] - recent["lowest"]) / recent["avg_price"])

    summary = recent.groupby("type_id").agg(
        price_mean=("avg_price", "mean"),
        price_std=("avg_price", "std"),
        daily_range_pct_mean=("daily_range_pct", "mean"),
        days_observed=("date", "count"),
    ).reset_index()

    summary["volatility_cv"] = (summary["price_std"] / summary["price_mean"]).fillna(0)
    return summary.sort_values("volatility_cv", ascending=False)
