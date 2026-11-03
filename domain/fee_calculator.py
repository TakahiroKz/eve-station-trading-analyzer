"""Calculo 3: Costes de la operacion (broker, sales tax, relist)."""
from __future__ import annotations

from dataclasses import dataclass

from domain.models import CostConfig


@dataclass
class FeeBreakdown:
    broker_fee_buy: float
    broker_fee_sell: float
    sales_tax: float
    relist_cost: float

    @property
    def total(self) -> float:
        return self.broker_fee_buy + self.broker_fee_sell + self.sales_tax + self.relist_cost


def calculate_fees(buy_price: float, sell_price: float, costs: CostConfig) -> FeeBreakdown:
    """Todas las tasas se aplican como porcentaje sobre el precio correspondiente a cada lado
    de la orden (buy fee sobre buy price, sell fee/tax sobre sell price), tal como opera EVE Online.
    """
    broker_fee_buy = buy_price * (costs.broker_fee_buy_pct / 100.0)
    broker_fee_sell = sell_price * (costs.broker_fee_sell_pct / 100.0)
    sales_tax = sell_price * (costs.sales_tax_pct / 100.0)
    relist_cost = sell_price * (costs.relist_fee_pct / 100.0)
    return FeeBreakdown(
        broker_fee_buy=broker_fee_buy,
        broker_fee_sell=broker_fee_sell,
        sales_tax=sales_tax,
        relist_cost=relist_cost,
    )
