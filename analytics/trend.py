"""Tendencia de precio por ítem y mercado, calculada sobre el histórico diario que ya se guarda.

Compara el precio medio ponderado por volumen (VWAP) de los últimos 7 días con el de los 7 días
anteriores. Es descriptiva, no una predicción: el estudio sobre el histórico real mostró que la
tendencia de una semana no anticipa la siguiente, pero sí dice si un precio se está moviendo y
evita comprar justo cuando el precio ya cae. Por eso el umbral para llamarla "sube" o "baja"
depende del ruido propio de cada ítem y no es un porcentaje fijo (un -2 % es ruido en un ítem
volátil y una señal fuerte en uno estable).

Etiquetas: up, down, flat, lowliq (pocas operaciones diarias: la cifra no es fiable) y nodata
(histórico insuficiente).
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

WINDOW_DAYS = 7
MIN_TRADING_DAYS = 4      # días con operaciones exigidos en cada ventana
MIN_TRADES = 7            # operaciones totales exigidas en cada ventana
MIN_NOISE_SAMPLES = 8     # variaciones diarias mínimas para estimar el ruido del ítem


@dataclass
class TrendConfig:
    # Nombres iguales a las keys de storage/settings_registry.py (ver scheduler/run.py).
    trend_noise_multiplier: float = 1.5
    trend_min_change_pct: float = 0.05
    trend_min_ops_per_day: float = 5.0


DEFAULT_CONFIG = TrendConfig()

TREND_COLUMNS = ["price_trend", "price_trend_label", "price_trend_threshold"]


def compute_price_trends(history: pd.DataFrame, config: TrendConfig = DEFAULT_CONFIG) -> pd.DataFrame:
    """Devuelve un DataFrame indexado por type_id con price_trend (fracción: 0.08 = +8 %),
    price_trend_label y price_trend_threshold (fracción). `history` trae type_id, date, avg_price,
    volume y order_count, con unas 30 filas por ítem. Las ventanas se miden contra la última fecha
    del mercado (no la de cada ítem) para que un ítem sin operaciones recientes no compare semanas
    antiguas como si fueran las actuales."""
    if history.empty:
        return pd.DataFrame(columns=TREND_COLUMNS, index=pd.Index([], name="type_id"))

    df = history[["type_id", "date", "avg_price", "volume", "order_count"]].copy()
    df["day"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[(df["avg_price"] > 0) & (df["volume"] > 0)]
    if df.empty:
        return pd.DataFrame(columns=TREND_COLUMNS, index=pd.Index([], name="type_id"))

    last_day = history["date"].max()
    last_day = pd.to_datetime(last_day).normalize()
    recent_start = last_day - pd.Timedelta(days=WINDOW_DAYS - 1)
    prev_start = last_day - pd.Timedelta(days=2 * WINDOW_DAYS - 1)

    df["window"] = np.where(
        df["day"] >= recent_start, "recent",
        np.where(df["day"] >= prev_start, "prev", "old"),
    )
    df["notional"] = df["avg_price"] * df["volume"]

    def window_stats(name: str) -> pd.DataFrame:
        part = df[df["window"] == name]
        grouped = part.groupby("type_id")
        out = pd.DataFrame({
            f"{name}_notional": grouped["notional"].sum(),
            f"{name}_volume": grouped["volume"].sum(),
            f"{name}_days": grouped["day"].nunique(),
            f"{name}_trades": grouped["order_count"].sum(),
        })
        out[f"{name}_vwap"] = out[f"{name}_notional"] / out[f"{name}_volume"]
        return out

    stats = pd.DataFrame(index=pd.Index(sorted(history["type_id"].unique()), name="type_id"))
    stats = stats.join(window_stats("recent")).join(window_stats("prev"))

    # Ruido propio de cada ítem: desviación de las variaciones diarias (log) del precio medio.
    ordered = df.sort_values(["type_id", "day"])
    ordered["log_price"] = np.log(ordered["avg_price"])
    ordered["log_return"] = ordered.groupby("type_id")["log_price"].diff()
    returns = ordered.dropna(subset=["log_return"]).groupby("type_id")["log_return"]
    sigma = returns.std(ddof=1).where(returns.count() >= MIN_NOISE_SAMPLES)
    stats["sigma"] = sigma

    # El error típico de la diferencia entre dos medias de 7 días es sigma * sqrt(2/7).
    noise = config.trend_noise_multiplier * stats["sigma"].fillna(0.0) * math.sqrt(2.0 / WINDOW_DAYS)
    stats["price_trend_threshold"] = np.maximum(config.trend_min_change_pct, noise)

    enough = (
        (stats["recent_days"].fillna(0) >= MIN_TRADING_DAYS)
        & (stats["prev_days"].fillna(0) >= MIN_TRADING_DAYS)
        & (stats["recent_trades"].fillna(0) >= MIN_TRADES)
        & (stats["prev_trades"].fillna(0) >= MIN_TRADES)
    )
    change = stats["recent_vwap"] / stats["prev_vwap"] - 1.0
    stats["price_trend"] = change.where(enough)

    ops_per_day = stats["recent_trades"].fillna(0) / WINDOW_DAYS
    label = pd.Series("flat", index=stats.index)
    label[stats["price_trend"] > stats["price_trend_threshold"]] = "up"
    label[stats["price_trend"] < -stats["price_trend_threshold"]] = "down"
    label[ops_per_day < config.trend_min_ops_per_day] = "lowliq"
    label[~enough] = "nodata"
    stats["price_trend_label"] = label

    # Sin dato fiable no se publica ni cifra ni umbral.
    stats.loc[~enough, ["price_trend", "price_trend_threshold"]] = np.nan
    return stats[TREND_COLUMNS]
