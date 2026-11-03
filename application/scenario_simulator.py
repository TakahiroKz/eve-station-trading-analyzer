"""Seccion 36-38: Simulador de operacion y escenarios optimista/esperado/pesimista."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from domain.breakeven_calculator import calculate_breakeven_sell_price
from domain.fee_calculator import calculate_fees
from domain.margin_calculator import calculate_net_margin_pct
from domain.models import CostConfig
from domain.profit_calculator import calculate_net_profit


@dataclass
class SimulationInput:
    capital: float
    buy_price: float
    sell_price: float
    quantity: int
    costs: CostConfig


@dataclass
class SimulationResult:
    capital_used: float
    total_cost: float
    revenue: float
    fees_total: float
    profit: float
    roi_pct: float
    margin_pct: float
    breakeven_sell_price: float


def simulate(inp: SimulationInput) -> SimulationResult:
    fees = calculate_fees(inp.buy_price, inp.sell_price, inp.costs)
    profit_result = calculate_net_profit(inp.buy_price, inp.sell_price, fees)
    capital_used = inp.buy_price * inp.quantity
    total_cost = capital_used + fees.broker_fee_buy * inp.quantity
    revenue = inp.sell_price * inp.quantity
    fees_total = fees.total * inp.quantity
    profit = profit_result.net_profit_unit * inp.quantity
    roi_pct = (profit / capital_used * 100.0) if capital_used > 0 else 0.0
    margin_pct = calculate_net_margin_pct(profit_result.net_profit_unit, inp.buy_price)
    breakeven = calculate_breakeven_sell_price(inp.buy_price, inp.costs)
    return SimulationResult(
        capital_used=capital_used,
        total_cost=total_cost,
        revenue=revenue,
        fees_total=fees_total,
        profit=profit,
        roi_pct=roi_pct,
        margin_pct=margin_pct,
        breakeven_sell_price=breakeven,
    )


@dataclass
class ScenarioRow:
    name: str
    sell_price: float
    profit: float


def simulate_scenarios(inp: SimulationInput, pessimistic_pct: float = -10.0, optimistic_pct: float = 10.0) -> List[ScenarioRow]:
    scenarios = []
    for name, pct in (
        ("Optimista", optimistic_pct),
        ("Esperado", 0.0),
        ("Pesimista", pessimistic_pct),
    ):
        sell = inp.sell_price * (1 + pct / 100.0)
        variant = SimulationInput(inp.capital, inp.buy_price, sell, inp.quantity, inp.costs)
        result = simulate(variant)
        scenarios.append(ScenarioRow(name=name, sell_price=sell, profit=result.profit))

    breakeven = calculate_breakeven_sell_price(inp.buy_price, inp.costs)
    scenarios.append(ScenarioRow(name="Break-even", sell_price=breakeven, profit=0.0))
    return scenarios
