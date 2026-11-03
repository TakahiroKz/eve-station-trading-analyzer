"""Spread de precios (compra/venta) a partir de market_snapshot."""
import pandas as pd

from analytics.eve_calculator import spread_bruto


def spread_summary(snapshot: pd.DataFrame) -> pd.DataFrame:
    """snapshot: columnas [type_id, captured_at, best_buy, best_sell, buy_volume, sell_volume],
    normalmente la última foto por type_id.
    """
    latest = snapshot.sort_values("captured_at").groupby("type_id").tail(1).copy()
    latest = latest.dropna(subset=["best_buy", "best_sell"])
    latest = latest[latest["best_buy"] > 0]

    latest["spread_bruto"] = latest.apply(
        lambda r: spread_bruto(r["best_buy"], r["best_sell"]), axis=1
    )
    return latest.sort_values("spread_bruto", ascending=False)
