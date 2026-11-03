"""Calculo 2 y 4: Beneficio bruto y neto por unidad."""
from __future__ import annotations

from dataclasses import dataclass

from domain.fee_calculator import FeeBreakdown


@dataclass
class ProfitResult:
    gross_profit_unit: float
    net_profit_unit: float
    fees: FeeBreakdown


def calculate_gross_profit(buy_price: float, sell_price: float) -> float:
    return sell_price - buy_price


def calculate_net_profit(buy_price: float, sell_price: float, fees: FeeBreakdown) -> ProfitResult:
    gross = calculate_gross_profit(buy_price, sell_price)
    net = gross - fees.total
    return ProfitResult(gross_profit_unit=gross, net_profit_unit=net, fees=fees)
