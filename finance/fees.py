"""Perfil del personaje y cálculo de comisiones, impuesto y relist (Decimal)."""
from dataclasses import dataclass
from decimal import Decimal

from finance.rules import DEFAULT_RULES, RuleSet

D = Decimal


def dec(value) -> Decimal:
    """Convierte a Decimal sin arrastrar el ruido binario de los float; rechaza NaN/inf."""
    if isinstance(value, Decimal):
        out = value
    elif isinstance(value, bool):
        raise ValueError("bool no es un número")
    else:
        out = Decimal(str(value))
    if not out.is_finite():
        raise ValueError("número no finito")
    return out


@dataclass(frozen=True)
class Profile:
    broker_relations: int = 2        # BR II = constantes históricas 0,901 / 1,024
    advanced_broker_relations: int = 0
    accounting: int = 0
    faction_standing: Decimal = D("0")
    corp_standing: Decimal = D("0")
    source: str = "MANUAL"           # MANUAL | ESI

    def validate(self, rules: RuleSet = DEFAULT_RULES) -> None:
        for name in ("broker_relations", "advanced_broker_relations", "accounting"):
            level = getattr(self, name)
            if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= rules.max_skill_level:
                raise ValueError(f"{name} debe ser un entero de 0 a {rules.max_skill_level}")
        for name in ("faction_standing", "corp_standing"):
            value = dec(getattr(self, name))
            if abs(value) > rules.max_standing:
                raise ValueError(f"{name} debe estar entre -10 y 10")
        if self.source not in ("MANUAL", "ESI"):
            raise ValueError("source debe ser MANUAL o ESI")


@dataclass(frozen=True)
class Venue:
    kind: str = "NPC"                 # NPC | UPWELL
    owner_fee_pct: Decimal | None = None   # fracción (0.01 = 1 %); obligatorio en UPWELL


def broker_fee_rate(profile: Profile, venue: Venue, rules: RuleSet = DEFAULT_RULES) -> Decimal | None:
    """Fracción de broker fee; None si falta un dato obligatorio (p. ej. el % del dueño de una Upwell)."""
    if venue.kind == "NPC":
        rate = (rules.npc_broker_base
                - rules.npc_broker_per_br_level * profile.broker_relations
                - rules.npc_broker_per_faction_standing * dec(profile.faction_standing)
                - rules.npc_broker_per_corp_standing * dec(profile.corp_standing))
        return max(rate, rules.npc_broker_floor)
    if venue.kind == "UPWELL":
        if venue.owner_fee_pct is None:
            return None
        owner = dec(venue.owner_fee_pct)
        if owner < 0:
            raise ValueError("owner_fee_pct no puede ser negativo")
        return rules.scc_surcharge + owner
    raise ValueError(f"tipo de lugar desconocido: {venue.kind}")


def sales_tax_rate(profile: Profile, rules: RuleSet = DEFAULT_RULES) -> Decimal:
    return rules.sales_tax_base * (1 - rules.sales_tax_reduction_per_accounting_level * profile.accounting)


def order_fee(value: Decimal, rate: Decimal, rules: RuleSet = DEFAULT_RULES) -> Decimal:
    """Broker fee de una orden: proporcional con mínimo de 100 ISK (si el valor es 0 no hay orden, no hay cobro)."""
    if value <= 0:
        return D("0")
    return max(value * rate, rules.min_order_fee)


def relist_discount(profile: Profile, rules: RuleSet = DEFAULT_RULES) -> Decimal:
    return min(D("1"), rules.relist_discount_base + rules.relist_discount_per_adv_level * profile.advanced_broker_relations)


def relist_fee(old_price: Decimal, new_price: Decimal, units: Decimal, rate: Decimal, profile: Profile,
               rules: RuleSet = DEFAULT_RULES) -> Decimal:
    """Cobro por modificar una orden de old_price a new_price: BR·max(0,P2−P1) + (1−RD)·BR·P2 (por unidad), mín. 100."""
    up = max(D("0"), new_price - old_price)
    per_unit = rate * up + (1 - relist_discount(profile, rules)) * rate * new_price
    return max(per_unit * units, rules.min_order_fee)
