"""Seccion 28: Hard Stops. Ninguna condicion critica puede quedar oculta por el score."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from domain.models import HardStopConfig
from domain.risk_analyzer import RatingLevel


@dataclass
class HardStopInputs:
    trend_pct: float
    volatility_pct: float
    net_margin_pct: float
    position_exceeds_capital: bool
    liquidity_level: RatingLevel


@dataclass
class HardStopViolation:
    code: str
    message: str


def evaluate_hard_stops(inputs: HardStopInputs, config: HardStopConfig) -> List[HardStopViolation]:
    violations: List[HardStopViolation] = []

    if inputs.trend_pct < config.trend_min_pct:
        violations.append(HardStopViolation(
            code="TREND_TOO_NEGATIVE",
            message=f"Tendencia ({inputs.trend_pct:.1f}%) por debajo del minimo permitido ({config.trend_min_pct:.1f}%).",
        ))

    if inputs.volatility_pct > config.volatility_max_pct:
        violations.append(HardStopViolation(
            code="VOLATILITY_TOO_HIGH",
            message=f"Volatilidad ({inputs.volatility_pct:.1f}%) supera el maximo permitido ({config.volatility_max_pct:.1f}%).",
        ))

    if inputs.net_margin_pct < config.net_margin_min_pct:
        violations.append(HardStopViolation(
            code="MARGIN_TOO_LOW",
            message=f"Margen neto ({inputs.net_margin_pct:.1f}%) por debajo del minimo requerido ({config.net_margin_min_pct:.1f}%).",
        ))

    if inputs.position_exceeds_capital:
        violations.append(HardStopViolation(
            code="POSITION_EXCEEDS_CAPITAL",
            message="El precio unitario o la posicion solicitada supera el limite de exposicion configurado.",
        ))

    if config.liquidity_insufficient_blocks and inputs.liquidity_level == RatingLevel.BAD:
        violations.append(HardStopViolation(
            code="LIQUIDITY_INSUFFICIENT",
            message="La liquidez del producto es insuficiente para garantizar una ejecucion razonable.",
        ))

    return violations
