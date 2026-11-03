"""Calculo 37: Break-even price. Precio minimo de venta que no genera perdidas."""
from __future__ import annotations

from domain.models import CostConfig


def calculate_breakeven_sell_price(buy_price: float, costs: CostConfig) -> float:
    """Resuelve sell_price tal que:
    sell_price - buy_price - broker_buy - broker_sell(sell_price) - tax(sell_price) - relist(sell_price) = 0

    broker_buy es fijo (sobre buy_price). Los costes del lado venta son porcentuales sobre sell_price,
    por lo que despejamos algebraicamente:
        sell_price * (1 - pct_sell_side) = buy_price + broker_fee_buy
    """
    broker_fee_buy = buy_price * (costs.broker_fee_buy_pct / 100.0)
    sell_side_pct = (
        costs.broker_fee_sell_pct + costs.sales_tax_pct + costs.relist_fee_pct
    ) / 100.0
    if sell_side_pct >= 1.0:
        raise ValueError("Los costes del lado de venta superan o igualan el 100%; break-even indefinido")
    return (buy_price + broker_fee_buy) / (1.0 - sell_side_pct)


def safety_margin_pct(current_sell_price: float, breakeven_price: float) -> float:
    if breakeven_price <= 0:
        raise ValueError("breakeven_price debe ser mayor que 0")
    return ((current_sell_price - breakeven_price) / breakeven_price) * 100.0
