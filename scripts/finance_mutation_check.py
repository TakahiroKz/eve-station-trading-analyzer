#!/usr/bin/env python3
"""Pruebas de mutación del motor financiero (finance/): introduce un fallo a la vez; si las pruebas siguen en verde,
falta una prueba. Reutiliza el mecanismo de scripts/mutation_check.py.

Uso (contenedor con dependencias de desarrollo, desde la raíz del repo):  python scripts/finance_mutation_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_check as mc  # noqa: E402

mc.TESTS = ["tests/test_finance_engine.py"]
mc.MUTATIONS = [
    ("el nivel de Broker Relations resta 0,2 % en vez de 0,3 %", "finance/rules.py",
     'npc_broker_per_br_level: Decimal = D("0.003")', 'npc_broker_per_br_level: Decimal = D("0.002")'),
    ("el standing de facción pesa como el de corporación", "finance/rules.py",
     'npc_broker_per_faction_standing: Decimal = D("0.0003")', 'npc_broker_per_faction_standing: Decimal = D("0.0002")'),
    ("el suelo del broker fee desaparece", "finance/fees.py",
     "return max(rate, rules.npc_broker_floor)", "return rate"),
    ("Accounting reduce 10 % por nivel en vez de 11 %", "finance/rules.py",
     'sales_tax_reduction_per_accounting_level: Decimal = D("0.11")',
     'sales_tax_reduction_per_accounting_level: Decimal = D("0.10")'),
    ("el sales tax base vuelve a 8 %", "finance/rules.py",
     'sales_tax_base: Decimal = D("0.075")', 'sales_tax_base: Decimal = D("0.08")'),
    ("el recargo SCC de Upwell se omite", "finance/fees.py",
     "return rules.scc_surcharge + owner", "return owner"),
    ("el cobro mínimo de 100 ISK no se aplica", "finance/fees.py",
     "return max(value * rate, rules.min_order_fee)", "return value * rate"),
    ("el descuento de relist ignora el nivel de Advanced Broker Relations", "finance/fees.py",
     "rules.relist_discount_per_adv_level * profile.advanced_broker_relations", "0"),
    ("el relist cobra solo la parte de subida", "finance/fees.py",
     "per_unit = rate * up + (1 - relist_discount(profile, rules)) * rate * new_price", "per_unit = rate * up"),
    ("la compra inmediata paga broker fee", "finance/profit.py",
     "buy_fee = order_fee(buy_cost, broker_rate, rules) if buy_limit else ZERO",
     "buy_fee = order_fee(buy_cost, broker_rate, rules)"),
    ("la venta inmediata no paga sales tax", "finance/profit.py",
     "tax = sell_gross * sales_tax_rate(profile, rules)", "tax = sell_gross * sales_tax_rate(profile, rules) if sell_limit else ZERO"),
    ("el ROI se calcula sobre la compra sin su comisión", "finance/profit.py",
     "outlay = buy_cost + buy_fee + relist_total", "outlay = buy_cost + relist_total"),
    ("el beneficio no resta el impuesto", "finance/profit.py",
     "total_costs = buy_cost + buy_fee + sell_fee + tax + relist_total",
     "total_costs = buy_cost + buy_fee + sell_fee + relist_total"),
    ("el libro compra consumiendo primero lo más caro", "finance/book.py",
     "return _walk(asks, dec(units), ascending=True)", "return _walk(asks, dec(units), ascending=False)"),
    ("el libro de venta consume primero lo más barato", "finance/book.py",
     "return _walk(bids, dec(units), ascending=False)", "return _walk(bids, dec(units), ascending=True)"),
    ("el precio de equilibrio ignora el mínimo de comisión", "finance/targets.py",
     "return max(needed / d_prop, (needed + rules.min_order_fee) / d_min)", "return needed / d_prop"),
    ("el precio máximo de compra ignora la comisión", "finance/targets.py",
     "price = min((budget - rules.min_order_fee) / units, budget / (units * (ONE + broker_rate)))",
     "price = budget / units"),
    ("las unidades máximas redondean hacia arriba", "finance/capital.py",
     "rounding=ROUND_FLOOR", "rounding=\"ROUND_CEILING\""),
    ("las unidades máximas olvidan el mínimo de comisión", "finance/capital.py",
     "q = min((available - rules.min_order_fee) / price, available / (price * (ONE + broker_rate)))",
     "q = available / (price * (ONE + broker_rate))"),
    ("un libro con hueco se da por completo (no avisa del faltante)", "finance/assessment.py",
     "        if fill.shortfall > 0:\n            out.warnings.append(f\"PARTIAL_FILL:asks", "        if False:\n            out.warnings.append(f\"PARTIAL_FILL:asks"),
    ("Upwell sin % del dueño se calcula igualmente", "finance/assessment.py",
     "    if rate is None:\n        return _incomplete(out, \"MISSING:owner_fee_pct\", used)", "    if rate is None:\n        rate = Decimal(0)"),
    ("la regla discrepante deja de avisar", "finance/assessment.py",
     'RULE_STATUS[r] != "CONFIRMADA"', "False"),
    ("el perfil aceptaría un nivel de habilidad inexistente", "finance/fees.py",
     "not 0 <= level <= rules.max_skill_level", "False"),
]

if __name__ == "__main__":
    sys.exit(mc.main())
