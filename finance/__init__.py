"""Motor financiero personalizado (EF-02): comisiones, impuestos, libro, beneficio, objetivos y capital.

Puro (sin E/S), en Decimal y determinista. Ver docs/EF02_REGLAS_DE_COMISIONES.md.
"""
from finance.assessment import FinancialAssessment, evaluate
from finance.rules import ENGINE_VERSION, RULES_VERSION

__all__ = ["ENGINE_VERSION", "RULES_VERSION", "FinancialAssessment", "evaluate"]
