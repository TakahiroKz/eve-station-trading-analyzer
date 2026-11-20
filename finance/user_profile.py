"""Perfil efectivo de un jugador para un mercado: habilidades y standings de ESI, con prioridad a lo que él corrija a mano.

Puro (sin E/S). Cada valor lleva su origen: MANUAL (lo escribió el jugador), ESI (leído de su personaje) o DEFAULT
(no hay dato; se usa el perfil por defecto del motor, el de las constantes históricas 0,901 / 1,024).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from finance.fees import Profile, Venue, broker_fee_rate, sales_tax_rate
from finance.hubs import Hub
from finance.rules import DEFAULT_RULES

SKILL_FIELDS = ("broker_relations", "advanced_broker_relations", "accounting")
_DEFAULT = Profile()


def _level(raw) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= DEFAULT_RULES.max_skill_level:
        return None
    return raw


def _standing(raw) -> Decimal | None:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or abs(value) > DEFAULT_RULES.max_standing:
        return None
    return value


def resolve_skills(esi: dict | None, manual: dict | None) -> dict[str, dict]:
    """{campo: {value, source}}; un valor corrupto en la base se ignora (cae al siguiente origen), no rompe al jugador."""
    out = {}
    for field in SKILL_FIELDS:
        m, e = _level((manual or {}).get(field)), _level((esi or {}).get(field))
        if m is not None:
            out[field] = {"value": m, "source": "MANUAL", "esi": e}
        elif e is not None:
            out[field] = {"value": e, "source": "ESI", "esi": e}
        else:
            out[field] = {"value": getattr(_DEFAULT, field), "source": "DEFAULT", "esi": None}
    return out


def resolve_standings(hub: Hub, esi: dict | None, manual: dict | None) -> dict[str, dict]:
    """Standing con la facción y con la corporación dueña de la estación de ese mercado."""
    manual = manual or {}
    esi = esi or {}
    out = {}
    for kind, ident in (("faction", hub.faction_id), ("corp", hub.owner_corp_id)):
        m = _standing(manual.get(kind)) if kind in manual else None
        e = _standing((esi.get(kind) or {}).get(str(ident))) if str(ident) in (esi.get(kind) or {}) else None
        if m is not None:
            out[kind] = {"value": m, "source": "MANUAL", "esi": e}
        elif e is not None:
            out[kind] = {"value": e, "source": "ESI", "esi": e}
        else:
            out[kind] = {"value": Decimal(0), "source": "DEFAULT", "esi": None}
    return out


def build_profile(hub: Hub, skills_esi: dict | None, standings_esi: dict | None, override: dict | None):
    """(Profile del motor, skills resueltas, standings resueltos) para un mercado."""
    override = override or {}
    skills = resolve_skills(skills_esi, override.get("skills"))
    standings = resolve_standings(hub, standings_esi, (override.get("standings") or {}).get(hub.market_id))
    all_esi = all(v["source"] == "ESI" for v in (*skills.values(), *standings.values()))
    profile = Profile(
        broker_relations=skills["broker_relations"]["value"],
        advanced_broker_relations=skills["advanced_broker_relations"]["value"],
        accounting=skills["accounting"]["value"],
        faction_standing=standings["faction"]["value"],
        corp_standing=standings["corp"]["value"],
        source="ESI" if all_esi else "MANUAL")
    profile.validate()
    return profile, skills, standings


def fee_summary(profile: Profile) -> dict:
    """Comisión de broker y sales tax (en %) de una estación NPC con este perfil."""
    broker = broker_fee_rate(profile, Venue("NPC"))
    tax = sales_tax_rate(profile)
    pct = Decimal("0.001")
    return {"broker_fee_pct": float((broker * 100).quantize(pct)), "sales_tax_pct": float((tax * 100).quantize(pct))}


def screener_factors(profile: Profile) -> tuple[float, float]:
    """(sales_tax_factor, buy_fee_factor) del Screener para este perfil: una compra y una venta con órdenes límite en una
    estación NPC. Con el perfil por defecto salen 0,901 y 1,024, las constantes históricas (prueba de regresión).
    Redondeados a 4 decimales: acota las variantes distintas que hay que calcular y cachear."""
    broker = broker_fee_rate(profile, Venue("NPC"))
    tax = sales_tax_rate(profile)
    step = Decimal("0.0001")
    return (float((1 - tax - broker).quantize(step, ROUND_HALF_UP)), float((1 + broker).quantize(step, ROUND_HALF_UP)))
