"""Seccion 27: Viability Score 0-100, con pesos configurables por factor."""
from __future__ import annotations

from dataclasses import dataclass

from domain.models import ScoreWeights


@dataclass
class ScoreSubfactors:
    """Cada subfactor normalizado en el rango 0-100 antes de ponderar."""
    net_margin_score: float
    profit_unit_score: float
    liquidity_score: float
    profit_day_score: float
    trend_score: float
    volatility_score: float
    capital_efficiency_score: float
    market_depth_score: float


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def normalize_linear(value: float, worst: float, best: float) -> float:
    """Escala 'value' linealmente a 0-100 entre worst (->0) y best (->100). Soporta escalas invertidas."""
    if best == worst:
        return 0.0
    pct = (value - worst) / (best - worst) * 100.0
    return _clamp(pct)


@dataclass
class ScoreResult:
    total_score: float
    subfactors: ScoreSubfactors
    weighted_breakdown: dict


def calculate_viability_score(subfactors: ScoreSubfactors, weights: ScoreWeights) -> ScoreResult:
    weight_map = {
        "net_margin": (subfactors.net_margin_score, weights.net_margin),
        "profit_unit": (subfactors.profit_unit_score, weights.profit_unit),
        "liquidity": (subfactors.liquidity_score, weights.liquidity),
        "profit_day": (subfactors.profit_day_score, weights.profit_day),
        "trend": (subfactors.trend_score, weights.trend),
        "volatility": (subfactors.volatility_score, weights.volatility),
        "capital_efficiency": (subfactors.capital_efficiency_score, weights.capital_efficiency),
        "market_depth": (subfactors.market_depth_score, weights.market_depth),
    }
    total_weight = sum(w for _, w in weight_map.values())
    if total_weight <= 0:
        raise ValueError("La suma de los pesos del score debe ser mayor que 0")

    breakdown = {}
    weighted_sum = 0.0
    for name, (score, weight) in weight_map.items():
        contribution = score * (weight / total_weight)
        breakdown[name] = contribution
        weighted_sum += contribution

    return ScoreResult(total_score=_clamp(weighted_sum), subfactors=subfactors, weighted_breakdown=breakdown)
