from domain.fee_calculator import calculate_fees
from domain.models import CostConfig
from domain.profit_calculator import calculate_gross_profit, calculate_net_profit


def make_costs(broker_buy=3.0, broker_sell=3.0, tax=3.6, relist=1.5):
    return CostConfig(
        broker_fee_buy_pct=broker_buy,
        broker_fee_sell_pct=broker_sell,
        sales_tax_pct=tax,
        relist_fee_pct=relist,
    )


def test_gross_profit():
    assert calculate_gross_profit(698_000, 997_900) == 299_900


def test_fees_breakdown():
    costs = make_costs()
    fees = calculate_fees(698_000, 997_900, costs)
    assert round(fees.broker_fee_buy, 2) == round(698_000 * 0.03, 2)
    assert round(fees.broker_fee_sell, 2) == round(997_900 * 0.03, 2)
    assert round(fees.sales_tax, 2) == round(997_900 * 0.036, 2)
    assert round(fees.relist_cost, 2) == round(997_900 * 0.015, 2)


def test_net_profit_lower_than_gross():
    costs = make_costs()
    fees = calculate_fees(698_000, 997_900, costs)
    result = calculate_net_profit(698_000, 997_900, fees)
    assert result.net_profit_unit < result.gross_profit_unit
    assert result.gross_profit_unit == 299_900


def test_zero_fees_net_equals_gross():
    costs = make_costs(0, 0, 0, 0)
    fees = calculate_fees(100, 200, costs)
    result = calculate_net_profit(100, 200, fees)
    assert result.net_profit_unit == result.gross_profit_unit == 100
