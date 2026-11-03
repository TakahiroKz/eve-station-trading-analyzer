"""Requisito 44: no confiar ciegamente en EVE-Hub. Compara valores observados vs calculados."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiscrepancyResult:
    eve_hub_value: float
    calculated_value: float
    difference: float
    difference_pct: float
    is_significant: bool


def compare_values(eve_hub_value: float, calculated_value: float, threshold_pct: float) -> DiscrepancyResult:
    difference = calculated_value - eve_hub_value
    base = abs(eve_hub_value) if eve_hub_value != 0 else 1.0
    difference_pct = (difference / base) * 100.0
    return DiscrepancyResult(
        eve_hub_value=eve_hub_value,
        calculated_value=calculated_value,
        difference=difference,
        difference_pct=difference_pct,
        is_significant=abs(difference_pct) > threshold_pct,
    )
