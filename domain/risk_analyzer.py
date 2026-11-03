"""Clasificaciones de tendencia, volatilidad, spread, liquidez, profundidad y tamano de posicion.

Todos los umbrales son configurables via ThresholdConfig (seccion 21-26 de la HU).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from domain.models import CapitalConfig, ThresholdConfig


class RatingLevel(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    NEUTRAL = "neutral"
    CAUTION = "caution"
    BAD = "bad"


@dataclass
class Rating:
    level: RatingLevel
    label: str
    emoji: str


def classify_trend(trend_pct: float, t: ThresholdConfig) -> Rating:
    if trend_pct > t.trend_favorable_min:
        return Rating(RatingLevel.EXCELLENT, "Favorable", "🟢")
    if trend_pct >= t.trend_neutral_min:
        return Rating(RatingLevel.GOOD, "Neutral/Favorable", "🟢")
    if trend_pct >= t.trend_caution_min:
        return Rating(RatingLevel.CAUTION, "Precaucion", "🟡")
    return Rating(RatingLevel.BAD, "Desfavorable", "🔴")


def classify_volatility(volatility_pct: float, t: ThresholdConfig) -> Rating:
    if volatility_pct < t.volatility_low_max:
        return Rating(RatingLevel.EXCELLENT, "Baja", "🟢")
    if volatility_pct <= t.volatility_medium_max:
        return Rating(RatingLevel.CAUTION, "Media", "🟡")
    return Rating(RatingLevel.BAD, "Alta", "🔴")


def classify_spread(spread_pct: float, t: ThresholdConfig) -> Rating:
    if spread_pct < t.spread_insufficient_max:
        return Rating(RatingLevel.BAD, "Insuficiente", "🔴")
    if spread_pct < t.spread_low_max:
        return Rating(RatingLevel.CAUTION, "Bajo", "🟡")
    if spread_pct < t.spread_good_max:
        return Rating(RatingLevel.EXCELLENT, "Bueno", "🟢")
    if spread_pct < t.spread_very_good_max:
        return Rating(RatingLevel.EXCELLENT, "Muy bueno", "🟢")
    return Rating(RatingLevel.CAUTION, "Investigar (spread anormalmente alto)", "🟡")


def classify_liquidity(volume_day: float, buy_depth: int, sell_depth: int) -> Rating:
    """No usa solo Volume/day: pondera tambien la profundidad de ambos lados del mercado."""
    depth_score = min(buy_depth, sell_depth)
    if volume_day >= 200 and depth_score >= 200:
        return Rating(RatingLevel.EXCELLENT, "Alta", "🟢")
    if volume_day >= 50 and depth_score >= 50:
        return Rating(RatingLevel.CAUTION, "Media", "🟡")
    return Rating(RatingLevel.BAD, "Baja", "🔴")


def classify_market_depth(units_ahead: int, volume_day: float) -> Rating:
    if volume_day <= 0:
        return Rating(RatingLevel.BAD, "Sin datos de volumen", "🔴")
    ratio_pct = (units_ahead / volume_day) * 100.0
    if ratio_pct < 15:
        return Rating(RatingLevel.EXCELLENT, "Buena", "🟢")
    if ratio_pct < 40:
        return Rating(RatingLevel.CAUTION, "Moderada", "🟡")
    return Rating(RatingLevel.BAD, "Congestionada", "🔴")


_RATING_SCORE_MAP = {
    RatingLevel.EXCELLENT: 100.0,
    RatingLevel.GOOD: 80.0,
    RatingLevel.NEUTRAL: 60.0,
    RatingLevel.CAUTION: 40.0,
    RatingLevel.BAD: 0.0,
}


def rating_to_score(rating: Rating) -> float:
    """Convierte una clasificacion cualitativa (verde/amarillo/rojo) en un subfactor 0-100
    para alimentar el Viability Score. Mapeo fijo y deterministico."""
    return _RATING_SCORE_MAP[rating.level]


@dataclass
class PositionCompatibility:
    compatible: bool
    max_capital_per_product: float
    unit_price: float


def evaluate_position_size(unit_price: float, capital: CapitalConfig) -> PositionCompatibility:
    max_capital = capital.total_isk * (capital.max_pct_per_product / 100.0)
    return PositionCompatibility(
        compatible=unit_price <= max_capital,
        max_capital_per_product=max_capital,
        unit_price=unit_price,
    )
