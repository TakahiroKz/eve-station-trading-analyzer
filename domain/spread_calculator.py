"""Calculo 1: Spread bruto. Funciones puras y deterministas."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpreadResult:
    spread_isk: float
    spread_pct: float


def calculate_spread(buy_price: float, sell_price: float) -> SpreadResult:
    if buy_price <= 0:
        raise ValueError("buy_price debe ser mayor que 0")
    spread_isk = sell_price - buy_price
    spread_pct = (spread_isk / buy_price) * 100.0
    return SpreadResult(spread_isk=spread_isk, spread_pct=spread_pct)
