import pytest

from domain.breakeven_calculator import calculate_breakeven_sell_price, safety_margin_pct
from domain.margin_calculator import calculate_net_margin_pct
from domain.models import CostConfig


def test_net_margin_conceptual_example():
    margin = calculate_net_margin_pct(net_profit_unit=170_000, buy_price=698_000)
    assert round(margin, 2) == round(170_000 / 698_000 * 100, 2)


def test_net_margin_zero_buy_raises():
    with pytest.raises(ValueError):
        calculate_net_margin_pct(100, 0)


def test_breakeven_zero_fees_equals_buy_price():
    costs = CostConfig(0, 0, 0, 0)
    be = calculate_breakeven_sell_price(698_000, costs)
    assert be == 698_000


def test_breakeven_with_fees_above_buy_price():
    costs = CostConfig(broker_fee_buy_pct=3.0, broker_fee_sell_pct=3.0, sales_tax_pct=3.6, relist_fee_pct=1.5)
    be = calculate_breakeven_sell_price(698_000, costs)
    assert be > 698_000


def test_safety_margin_positive_when_sell_above_breakeven():
    assert safety_margin_pct(current_sell_price=1000, breakeven_price=800) == pytest.approx(25.0)
