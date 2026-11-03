"""Seccion 29-33: Decision Engine. Combina score + hard stops + factores explicados
en una recomendacion explicable de 4 estados: BUY, BUY_WITH_CAUTION, WATCH, DO_NOT_BUY.

Regla fundamental (no negociable, seccion 47 de la HU):
El sistema NO debe recomendar una operacion basandose exclusivamente en Margin, Profit/Unit
o Profit/Day. Debe considerar simultaneamente rentabilidad, liquidez, profundidad de mercado,
tendencia, volatilidad, coste de capital y limites de exposicion. La recomendacion debe ser
explicable y todos los calculos economicos son deterministas (ver domain/*).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from domain.hard_stops import HardStopViolation
from domain.models import ThresholdConfig
from domain.risk_analyzer import Rating, RatingLevel
from domain.score_engine import ScoreResult


class RecommendationStatus(str, Enum):
    BUY = "BUY"
    BUY_WITH_CAUTION = "BUY_WITH_CAUTION"
    WATCH = "WATCH"
    DO_NOT_BUY = "DO_NOT_BUY"


STATUS_LABELS = {
    RecommendationStatus.BUY: ("🟢 COMPRAR", "green"),
    RecommendationStatus.BUY_WITH_CAUTION: ("🟡 COMPRAR CON PRECAUCION", "yellow"),
    RecommendationStatus.WATCH: ("🔵 OBSERVAR", "blue"),
    RecommendationStatus.DO_NOT_BUY: ("🔴 NO COMPRAR", "red"),
}


@dataclass
class ExplainedFactor:
    name: str
    rating: Rating
    detail: str


@dataclass
class RecommendationResult:
    status: RecommendationStatus
    label: str
    confidence: float
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    hard_stop_messages: List[str] = field(default_factory=list)
    cancel_condition: str = ""
    narrative: str = ""


def _split_factors(factors: List[ExplainedFactor]):
    reasons = [f"{f.detail}" for f in factors if f.rating.level in (RatingLevel.EXCELLENT, RatingLevel.GOOD)]
    risks = [f"{f.detail}" for f in factors if f.rating.level in (RatingLevel.CAUTION, RatingLevel.BAD)]
    return reasons, risks


def build_recommendation(
    score_result: ScoreResult,
    hard_stop_violations: List[HardStopViolation],
    factors: List[ExplainedFactor],
    thresholds: ThresholdConfig,
    cancel_condition: str = "",
) -> RecommendationResult:
    reasons, risks = _split_factors(factors)
    hard_stop_messages = [v.message for v in hard_stop_violations]
    score = score_result.total_score

    if hard_stop_violations:
        status = RecommendationStatus.DO_NOT_BUY
        confidence = min(score, 30.0)
        narrative = (
            "Existe al menos una condicion critica (hard stop) que hace esta operacion "
            "incompatible con la estrategia de riesgo configurada, independientemente del score obtenido."
        )
    elif score >= thresholds.score_buy_min and not any(
        f.rating.level in (RatingLevel.CAUTION, RatingLevel.BAD) for f in factors
    ):
        status = RecommendationStatus.BUY
        confidence = score
        narrative = "La rentabilidad, liquidez, riesgo, capital y profundidad de mercado son compatibles con la estrategia."
    elif score >= thresholds.score_caution_min:
        status = RecommendationStatus.BUY_WITH_CAUTION
        confidence = score
        narrative = (
            "Existe una oportunidad interesante, pero uno o varios factores requieren atencion "
            "antes de comprometer capital adicional."
        )
    elif score >= thresholds.score_watch_min:
        status = RecommendationStatus.WATCH
        confidence = score
        narrative = "La oportunidad es interesante pero todavia necesita confirmacion de estabilidad antes de invertir."
    else:
        status = RecommendationStatus.DO_NOT_BUY
        confidence = score
        narrative = "Los indicadores combinados no alcanzan el nivel minimo requerido por la estrategia."

    label, _ = STATUS_LABELS[status]

    return RecommendationResult(
        status=status,
        label=label,
        confidence=confidence,
        reasons=reasons,
        risks=risks,
        hard_stop_messages=hard_stop_messages,
        cancel_condition=cancel_condition,
        narrative=narrative,
    )
