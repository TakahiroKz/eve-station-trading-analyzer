"""Beneficio neto, ROI sobre el capital financiado y márgenes. Cada coste se cuenta una sola vez."""
from dataclasses import dataclass
from decimal import Decimal

from finance.fees import Profile, order_fee, relist_fee, sales_tax_rate
from finance.rules import DEFAULT_RULES, RuleSet

ZERO = Decimal(0)


@dataclass(frozen=True)
class Relist:
    side: str            # BUY | SELL
    old_price: Decimal
    new_price: Decimal


@dataclass(frozen=True)
class TradeResult:
    units: Decimal
    buy_cost: Decimal
    buy_fee: Decimal
    sell_gross: Decimal
    sell_fee: Decimal
    sales_tax: Decimal
    relist_fees: Decimal
    total_costs: Decimal         # compra + todas las comisiones e impuestos
    net_profit: Decimal
    capital_outlay: Decimal      # compra + comisión de compra + relists (base del ROI)
    roi: Decimal | None
    margin: Decimal | None       # beneficio neto / ingreso bruto


def compute_trade(units: Decimal, buy_price: Decimal, sell_price: Decimal, *, buy_limit: bool, sell_limit: bool,
                  broker_rate: Decimal, profile: Profile, relists: tuple[Relist, ...] = (),
                  rules: RuleSet = DEFAULT_RULES) -> TradeResult:
    buy_cost = units * buy_price
    sell_gross = units * sell_price
    buy_fee = order_fee(buy_cost, broker_rate, rules) if buy_limit else ZERO
    sell_fee = order_fee(sell_gross, broker_rate, rules) if sell_limit else ZERO
    tax = sell_gross * sales_tax_rate(profile, rules)
    relist_total = ZERO
    for r in relists:
        relist_total += relist_fee(r.old_price, r.new_price, units, broker_rate, profile, rules)
    total_costs = buy_cost + buy_fee + sell_fee + tax + relist_total
    net = sell_gross - total_costs
    outlay = buy_cost + buy_fee + relist_total
    return TradeResult(units, buy_cost, buy_fee, sell_gross, sell_fee, tax, relist_total, total_costs, net, outlay,
                       (net / outlay) if outlay > 0 else None,
                       (net / sell_gross) if sell_gross > 0 else None)
