from domain.models import CostConfig
from application.scenario_simulator import SimulationInput, simulate, simulate_scenarios


def make_costs():
    return CostConfig(broker_fee_buy_pct=3.0, broker_fee_sell_pct=3.0, sales_tax_pct=3.6, relist_fee_pct=1.5)


def test_simulate_basic():
    inp = SimulationInput(capital=50_000_000, buy_price=698_000, sell_price=997_900, quantity=7, costs=make_costs())
    result = simulate(inp)
    assert result.capital_used == 698_000 * 7
    assert result.profit > 0
    assert result.breakeven_sell_price > inp.buy_price


def test_scenarios_pessimistic_lower_than_optimistic():
    inp = SimulationInput(capital=50_000_000, buy_price=698_000, sell_price=997_900, quantity=7, costs=make_costs())
    scenarios = simulate_scenarios(inp)
    by_name = {s.name: s.profit for s in scenarios}
    assert by_name["Optimista"] > by_name["Esperado"] > by_name["Pesimista"]
    assert by_name["Break-even"] == 0.0
