"""Reglas de comisiones/impuestos con fuente y estado de verificación (docs/EF02_REGLAS_DE_COMISIONES.md)."""
from dataclasses import dataclass
from decimal import Decimal

ENGINE_VERSION = "1.0.0"
RULES_VERSION = "2026-11-19.1"

D = Decimal


@dataclass(frozen=True)
class RuleSet:
    npc_broker_base: Decimal = D("0.03")
    npc_broker_per_br_level: Decimal = D("0.003")
    npc_broker_per_faction_standing: Decimal = D("0.0003")
    npc_broker_per_corp_standing: Decimal = D("0.0002")
    npc_broker_floor: Decimal = D("0.01")
    min_order_fee: Decimal = D("100")
    sales_tax_base: Decimal = D("0.075")
    sales_tax_reduction_per_accounting_level: Decimal = D("0.11")
    scc_surcharge: Decimal = D("0.005")
    relist_discount_base: Decimal = D("0.50")
    relist_discount_per_adv_level: Decimal = D("0.06")
    max_skill_level: int = 5
    max_standing: Decimal = D("10")


# Estado de cada regla (clave R# del documento). Las que no son CONFIRMADA generan UNVERIFIED_RULE:R# al usarse.
RULE_STATUS = {
    "R1": "CONFIRMADA", "R2": "CONFIRMADA", "R3": "SUPUESTO", "R4": "CONFIRMADA", "R5": "CONFIRMADA",
    "R6": "DISCREPANTE", "R7": "CONFIRMADA", "R8": "DISCREPANTE", "R9": "SUPUESTO", "R10": "SUPUESTO",
    "R11": "SUPUESTO", "R12": "SUPUESTO",
}

DEFAULT_RULES = RuleSet()
CENT = D("0.01")
