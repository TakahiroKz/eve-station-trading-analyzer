"""Precios objetivo con comisión mínima (la función es 'mínimo de dos rectas', se resuelve en forma cerrada)."""
from decimal import Decimal

from finance.rules import DEFAULT_RULES, RuleSet

ONE = Decimal(1)


def min_sell_price(units: Decimal, buy_outlay: Decimal, *, tax_rate: Decimal, broker_rate: Decimal,
                   sell_limit: bool = True, target_roi: Decimal = Decimal(0),
                   rules: RuleSet = DEFAULT_RULES) -> Decimal | None:
    """Precio de venta mínimo por unidad para ganar target_roi sobre buy_outlay. None si es imposible."""
    needed = buy_outlay * (ONE + target_roi)          # ingreso neto requerido
    if not sell_limit:
        denom = units * (ONE - tax_rate)
        return needed / denom if denom > 0 else None
    d_prop = units * (ONE - broker_rate - tax_rate)
    d_min = units * (ONE - tax_rate)
    if d_prop <= 0 or d_min <= 0:
        return None
    # net(s) = min(rama proporcional, rama con mínimo): se cumple el objetivo cuando ambas lo cumplen.
    return max(needed / d_prop, (needed + rules.min_order_fee) / d_min)


def max_buy_price(units: Decimal, sell_net_revenue: Decimal, *, broker_rate: Decimal, buy_limit: bool = True,
                  target_roi: Decimal = Decimal(0), rules: RuleSet = DEFAULT_RULES) -> Decimal | None:
    """Precio de compra máximo por unidad para que (ingreso neto − desembolso) ≥ target_roi × desembolso."""
    if units <= 0:
        return None
    budget = sell_net_revenue / (ONE + target_roi)    # desembolso máximo
    if not buy_limit:
        return budget / units
    price = min((budget - rules.min_order_fee) / units, budget / (units * (ONE + broker_rate)))
    return price if price > 0 else None
