"""Calculo 5: Margen neto."""
from __future__ import annotations


def calculate_net_margin_pct(net_profit_unit: float, buy_price: float) -> float:
    if buy_price <= 0:
        raise ValueError("buy_price debe ser mayor que 0")
    return (net_profit_unit / buy_price) * 100.0
