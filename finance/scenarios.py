"""Escenarios: variaciones independientes sobre una misma entrada (no se mutan entre sí)."""
from dataclasses import replace

from finance.assessment import FinancialAssessment, TradeInput, evaluate


def run_scenarios(base: TradeInput, variations: dict[str, dict]) -> dict[str, FinancialAssessment]:
    out = {"base": evaluate(base)}
    for name, overrides in variations.items():
        if name == "base":
            raise ValueError("'base' está reservado")
        out[name] = evaluate(replace(base, **overrides))
    return out
