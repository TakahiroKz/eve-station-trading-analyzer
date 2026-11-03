"""Calculo 8, 9 y 10: Capital efficiency (ROI), profit/day estimado y capital turnover."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CapitalEfficiencyResult:
    capital_used: float
    estimated_profit: float
    roi_pct: float


def calculate_capital_efficiency(capital_used: float, net_profit_unit: float, units: int) -> CapitalEfficiencyResult:
    if capital_used <= 0:
        raise ValueError("capital_used debe ser mayor que 0")
    estimated_profit = net_profit_unit * units
    roi_pct = (estimated_profit / capital_used) * 100.0
    return CapitalEfficiencyResult(capital_used=capital_used, estimated_profit=estimated_profit, roi_pct=roi_pct)


def estimate_profit_per_day(net_profit_unit: float, expected_units_sold_per_day: float) -> float:
    """Estimacion basada en volumen historico; no representa una garantia de ejecucion."""
    return net_profit_unit * expected_units_sold_per_day


@dataclass
class CapitalTurnoverResult:
    days_to_recover: Optional[float]
    label: str = "Estimacion teorica de recuperacion"


def calculate_capital_turnover(capital_invested: float, estimated_profit_per_day: float) -> CapitalTurnoverResult:
    if estimated_profit_per_day <= 0:
        return CapitalTurnoverResult(days_to_recover=None)
    return CapitalTurnoverResult(days_to_recover=capital_invested / estimated_profit_per_day)
