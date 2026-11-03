import pytest

from domain.models import CapitalConfig
from domain.position_sizer import (
    calculate_max_capital_per_product,
    calculate_max_units,
    calculate_position_size,
)


def make_capital():
    return CapitalConfig(
        total_isk=50_000_000,
        trading_isk=30_000_000,
        reserve_isk=20_000_000,
        max_pct_per_position=10.0,
        max_pct_per_product=10.0,
    )


def test_max_capital_per_product():
    assert calculate_max_capital_per_product(make_capital()) == 5_000_000


def test_max_units_gamma_l_example():
    max_capital = calculate_max_capital_per_product(make_capital())
    units = calculate_max_units(698_000, max_capital)
    assert units == 7


def test_position_size_participation_pct():
    result = calculate_position_size(698_000, make_capital(), volume_day=390, requested_units=7)
    assert round(result.position_vs_volume_pct, 2) == pytest.approx(1.79, abs=0.01)


def test_position_exceeds_capital_flag():
    capital = make_capital()
    result = calculate_position_size(7_460_000, capital, volume_day=390, requested_units=1)
    assert result.exceeds_capital_limit is True
