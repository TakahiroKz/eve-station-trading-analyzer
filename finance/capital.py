"""Capital y coste de órdenes. El saldo de ESI ya excluye el escrow de las compras abiertas: no se resta dos veces."""
from decimal import ROUND_FLOOR, Decimal

from finance.fees import order_fee
from finance.rules import DEFAULT_RULES, RuleSet

ONE = Decimal(1)


def cost_of_buy_order(units: Decimal, price: Decimal, broker_rate: Decimal, rules: RuleSet = DEFAULT_RULES) -> Decimal:
    """Efectivo que se necesita para abrir la orden: escrow del 100 % + broker fee (que no entra en el escrow)."""
    value = units * price
    return value + order_fee(value, broker_rate, rules)


def max_units(available: Decimal, price: Decimal, broker_rate: Decimal, rules: RuleSet = DEFAULT_RULES) -> int:
    """Mayor número entero de unidades cuya orden de compra cabe en 'available' (con comisión mínima)."""
    if price <= 0 or available <= 0:
        return 0
    q = min((available - rules.min_order_fee) / price, available / (price * (ONE + broker_rate)))
    return max(0, int(q.to_integral_value(rounding=ROUND_FLOOR))) if q > 0 else 0


def available_capital(wallet: Decimal, reserved_by_user: Decimal = Decimal(0)) -> Decimal:
    """Capital utilizable: saldo del wallet (sin escrow) menos lo que el usuario aparta; nunca negativo."""
    return max(Decimal(0), wallet - reserved_by_user)
