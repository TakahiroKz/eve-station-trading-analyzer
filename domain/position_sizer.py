"""Calculo 6 y 7: Cantidad maxima comprable y participacion en el volumen."""
from __future__ import annotations

import math
from dataclasses import dataclass

from domain.models import CapitalConfig


@dataclass
class PositionSizeResult:
    max_capital_per_product: float
    max_units_by_capital: int
    capital_used: float
    position_vs_volume_pct: float
    exceeds_capital_limit: bool


def calculate_max_capital_per_product(capital: CapitalConfig) -> float:
    return capital.total_isk * (capital.max_pct_per_product / 100.0)


def calculate_max_units(buy_price: float, max_capital_per_product: float) -> int:
    if buy_price <= 0:
        raise ValueError("buy_price debe ser mayor que 0")
    return math.floor(max_capital_per_product / buy_price)


def calculate_position_size(
    buy_price: float,
    capital: CapitalConfig,
    volume_day: float,
    requested_units: int | None = None,
) -> PositionSizeResult:
    max_capital = calculate_max_capital_per_product(capital)
    max_units = calculate_max_units(buy_price, max_capital)
    units = requested_units if requested_units is not None else max_units
    capital_used = units * buy_price
    position_vs_volume_pct = (units / volume_day * 100.0) if volume_day > 0 else float("inf")
    exceeds = capital_used > max_capital
    return PositionSizeResult(
        max_capital_per_product=max_capital,
        max_units_by_capital=max_units,
        capital_used=capital_used,
        position_vs_volume_pct=position_vs_volume_pct,
        exceeds_capital_limit=exceeds,
    )
