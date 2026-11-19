"""Motor financiero EF-02: vectores hechos a mano, regresión con el motor histórico y propiedades aleatorias."""
import json
import random
from dataclasses import replace
from decimal import Decimal as D

import pytest

from analytics.eve_calculator import DEFAULT_CONFIG, beneficio_unitario, roi as legacy_roi
from finance import ENGINE_VERSION, RULES_VERSION, book, capital, evaluate, targets
from finance.assessment import TradeInput
from finance.fees import Profile, Venue, broker_fee_rate, relist_discount, relist_fee, sales_tax_rate
from finance.profit import compute_trade
from finance.rules import DEFAULT_RULES
from finance.scenarios import run_scenarios

NPC = Venue("NPC")


def ev(**kw):
    kw.setdefault("units", 1000)
    kw.setdefault("buy_price", "100")
    kw.setdefault("sell_price", "125")
    return evaluate(TradeInput(**kw))


# ---- Reglas de comisiones (vectores a mano) -------------------------------------------------------------------

def test_broker_relations_levels():
    assert broker_fee_rate(Profile(broker_relations=0), NPC) == D("0.03")
    assert broker_fee_rate(Profile(broker_relations=5), NPC) == D("0.015")


def test_standings_reduce_fee_and_floor_applies():
    p = Profile(broker_relations=0, faction_standing=D("5"), corp_standing=D("4"))
    assert broker_fee_rate(p, NPC) == D("0.0277")
    assert broker_fee_rate(Profile(broker_relations=5, faction_standing=D("10"), corp_standing=D("10")), NPC) == D("0.010")
    # Un standing negativo encarece.
    assert broker_fee_rate(Profile(broker_relations=0, faction_standing=D("-10")), NPC) == D("0.033")


def test_accounting_levels():
    assert sales_tax_rate(Profile(accounting=0)) == D("0.075")
    assert sales_tax_rate(Profile(accounting=5)) == D("0.03375")


def test_upwell_needs_owner_fee_and_ignores_skills():
    assert broker_fee_rate(Profile(broker_relations=5), Venue("UPWELL", None)) is None
    assert broker_fee_rate(Profile(broker_relations=0), Venue("UPWELL", D("0.01"))) == D("0.015")
    assert broker_fee_rate(Profile(broker_relations=5), Venue("UPWELL", D("0.01"))) == D("0.015")


def test_relist_formula_and_discount():
    p = Profile(advanced_broker_relations=0)
    assert relist_discount(p) == D("0.50")
    # sube de 100 a 110, 10 000 unidades, 2,4 %: (0,024·10 + 0,5·0,024·110)·10 000 = 15 600
    assert relist_fee(D("100"), D("110"), D("10000"), D("0.024"), p) == D("15600.000")
    # bajar el precio solo paga la parte (1−RD)
    assert relist_fee(D("110"), D("100"), D("10000"), D("0.024"), p) == D("12000.000")
    assert relist_fee(D("100"), D("101"), D("1"), D("0.024"), p) == D("100")      # mínimo de 100 ISK


# ---- Cálculo de un trade ---------------------------------------------------------------------------------------

def test_default_profile_hand_computed_trade():
    a = ev()
    r = a.result
    assert a.calculation_status == "VALID"
    assert (r["buy_cost"], r["buy_fee"], r["sell_gross"], r["sell_fee"], r["sales_tax"]) == (
        D("100000.00"), D("2400.00"), D("125000.00"), D("3000.00"), D("9375.00"))
    assert r["net_profit"] == D("10225.00") and r["capital_outlay"] == D("102400.00")
    assert r["roi"] == D("0.099854") and r["margin"] == D("0.081800")
    assert a.engine_version == ENGINE_VERSION and a.rules_version == RULES_VERSION


def test_default_profile_reproduces_the_legacy_factors():
    """BR II, Accounting 0, standings 0 en NPC == las constantes 0,901 / 1,024 de analytics/eve_calculator.py."""
    p = Profile()
    rate, tax = broker_fee_rate(p, NPC), sales_tax_rate(p)
    assert 1 - tax - rate == D("0.901") and 1 + rate == D("1.024")
    assert float(1 - tax - rate) == DEFAULT_CONFIG.sales_tax_factor and float(1 + rate) == DEFAULT_CONFIG.buy_fee_factor


def test_matches_legacy_profit_and_roi_over_random_markets():
    rng = random.Random(20261119)
    for _ in range(3000):
        buy = round(10 ** rng.uniform(2, 8), 2)
        sell = round(buy * (1 + rng.uniform(-0.2, 3)), 2)
        units = rng.randint(1000, 5000)
        a = ev(units=units, buy_price=str(buy), sell_price=str(sell))
        per_unit = D(str(a.result["net_profit"])) / units
        assert abs(float(per_unit) - beneficio_unitario(buy, sell)) < 0.01 + 1e-9 * buy
        spread = sell / buy - 1
        assert abs(float(a.result["roi"]) - legacy_roi(spread, DEFAULT_CONFIG)) < 1e-5


def test_minimum_order_fee_applies_to_both_orders():
    a = ev(units=1, buy_price="100", sell_price="150")
    assert a.result["buy_fee"] == D("100.00") and a.result["sell_fee"] == D("100.00")
    assert a.result["net_profit"] == D("150") - D("100") - D("100") - D("100") - D("11.25")


def test_no_double_counting_total_costs_decompose():
    r = ev(relists=(("SELL", "125", "120"),)).result
    parts = sum(D(str(r[k])) for k in ("buy_cost", "buy_fee", "sell_fee", "sales_tax", "relist_fees"))
    assert abs(parts - D(str(r["total_costs"]))) <= D("0.03")
    assert abs(D(str(r["sell_gross"])) - D(str(r["total_costs"])) - D(str(r["net_profit"]))) <= D("0.03")


def test_better_skills_never_reduce_profit():
    base = ev(profile=Profile(broker_relations=0)).result["net_profit"]
    prev = base
    for level in range(1, 6):
        cur = ev(profile=Profile(broker_relations=level)).result["net_profit"]
        assert cur >= prev
        prev = cur
    assert ev(profile=Profile(accounting=5)).result["net_profit"] > ev(profile=Profile(accounting=0)).result["net_profit"]


def test_loss_is_flagged():
    a = ev(buy_price="100", sell_price="105")
    assert a.result["net_profit"] < 0 and "LOSS" in a.warnings


# ---- Libro y operaciones inmediatas --------------------------------------------------------------------------

def test_book_walks_levels_and_reports_shortfall():
    f = book.buy_immediate([(11, 5), (10, 5)], 8)
    assert f.total == D("83") and f.average_price == D("10.375") and f.shortfall == 0 and f.levels_used == 2
    g = book.sell_immediate([(10, 3), (12, 2)], 9)
    assert g.filled == D("5") and g.shortfall == D("4") and g.total == D("54")
    assert book.buy_immediate([], 3).average_price is None


def test_immediate_trades_pay_no_broker_fee():
    a = ev(units=10, buy_mode="IMMEDIATE", asks=[(100, 10)], sell_mode="IMMEDIATE", bids=[(120, 10)])
    r = a.result
    assert r["buy_fee"] == D("0.00") and r["sell_fee"] == D("0.00") and r["sales_tax"] == D("90.00")
    assert r["net_profit"] == D("1200") - D("1000") - D("90")
    assert "UNVERIFIED_RULE:R9" in a.warnings


def test_partial_fill_reduces_units_and_warns():
    a = ev(units=100, buy_mode="IMMEDIATE", asks=[(10, 30)], sell_price="20")
    assert a.result["units"] == D("30") and any(w.startswith("PARTIAL_FILL:asks") for w in a.warnings)
    b = ev(units=100, buy_price="10", sell_mode="IMMEDIATE", bids=[(20, 40)])
    assert b.result["units"] == D("40") and any(w.startswith("PARTIAL_FILL:bids") for w in b.warnings)


def test_empty_book_is_incomplete_not_invented():
    a = ev(buy_mode="IMMEDIATE", asks=[])
    assert a.calculation_status == "INCOMPLETE" and a.result is None and "NO_LIQUIDITY:asks" in a.warnings


# ---- Datos que faltan, estados y advertencias ------------------------------------------------------------------

def test_upwell_without_owner_fee_is_incomplete():
    a = ev(venue=Venue("UPWELL", None))
    assert a.calculation_status == "INCOMPLETE" and a.result is None
    assert "MISSING:owner_fee_pct" in a.warnings and "UNVERIFIED_RULE:R6" in a.warnings


def test_upwell_with_owner_fee_computes_and_warns():
    a = ev(venue=Venue("UPWELL", D("0.01")))
    assert a.calculation_status == "VALID" and a.rates["broker_fee"] == D("0.015")
    assert "UNVERIFIED_RULE:R6" in a.warnings


def test_missing_prices_are_incomplete():
    assert evaluate(TradeInput(units=1, sell_price="10")).warnings == ["MISSING:buy_price"]
    assert evaluate(TradeInput(units=1, buy_price="10")).warnings == ["MISSING:sell_price"]


def test_relist_triggers_unverified_rule_warning():
    assert "UNVERIFIED_RULE:R8" in ev(relists=(("BUY", "100", "101"),)).warnings
    assert not any(w.startswith("UNVERIFIED") for w in ev().warnings)


@pytest.mark.parametrize("kw", [
    {"units": 0}, {"units": -3}, {"units": 1.5}, {"units": float("nan")}, {"units": float("inf")},
    {"buy_price": "-1"}, {"sell_price": "0"}, {"buy_mode": "MAGIC"}, {"target_roi": -1},
    {"profile": Profile(broker_relations=6)}, {"profile": Profile(accounting=-1)},
    {"profile": Profile(faction_standing=D("11"))}, {"profile": Profile(source="HACK")},
    {"venue": Venue("UPWELL", D("-0.01"))}, {"venue": Venue("MOON")},
    {"relists": (("BUY", "0", "1"),)}, {"relists": (("LEFT", "1", "1"),)},
])
def test_invalid_inputs_are_rejected(kw):
    with pytest.raises(ValueError):
        ev(**kw)


def test_assessment_is_json_serialisable_and_snapshots_the_parameters():
    d = ev(profile=Profile(broker_relations=4, accounting=3, source="ESI")).to_dict()
    json.dumps(d)
    assert d["parameters"]["profile"]["source"] == "ESI" and d["parameters"]["profile"]["accounting"] == 3
    assert d["parameters"]["units"] == "1000"


# ---- Objetivos y capital ---------------------------------------------------------------------------------------

def test_break_even_sell_price_gives_zero_profit():
    rng = random.Random(5)
    for _ in range(2000):
        p = Profile(rng.randint(0, 5), 0, rng.randint(0, 5), D(rng.randint(-10, 10)), D(rng.randint(-10, 10)))
        rate, tax = broker_fee_rate(p, NPC), sales_tax_rate(p)
        units = D(rng.randint(1, 5000))
        buy = D(str(round(10 ** rng.uniform(0, 7), 2)))
        t = compute_trade(units, buy, buy, buy_limit=True, sell_limit=True, broker_rate=rate, profile=p)
        s = targets.min_sell_price(units, t.capital_outlay, tax_rate=tax, broker_rate=rate)
        at = compute_trade(units, buy, s, buy_limit=True, sell_limit=True, broker_rate=rate, profile=p)
        assert abs(at.net_profit) < D("1e-9"), (p, units, buy)
        above = compute_trade(units, buy, s * D("1.001"), buy_limit=True, sell_limit=True, broker_rate=rate, profile=p)
        assert above.net_profit > 0


def test_target_sell_price_reaches_the_target_roi_exactly():
    rng = random.Random(6)
    for _ in range(1000):
        p = Profile(rng.randint(0, 5), 0, rng.randint(0, 5))
        rate, tax = broker_fee_rate(p, NPC), sales_tax_rate(p)
        units, buy = D(rng.randint(1, 3000)), D(str(round(10 ** rng.uniform(0, 6), 2)))
        goal = D(str(round(rng.uniform(0, 1), 3)))
        outlay = compute_trade(units, buy, buy, buy_limit=True, sell_limit=True, broker_rate=rate, profile=p).capital_outlay
        s = targets.min_sell_price(units, outlay, tax_rate=tax, broker_rate=rate, target_roi=goal)
        at = compute_trade(units, buy, s, buy_limit=True, sell_limit=True, broker_rate=rate, profile=p)
        assert abs(at.roi - goal) < D("1e-12")


def test_max_buy_price_round_trip():
    rng = random.Random(7)
    for _ in range(1000):
        p = Profile(rng.randint(0, 5), 0, rng.randint(0, 5))
        rate = broker_fee_rate(p, NPC)
        units, sell = D(rng.randint(1, 3000)), D(str(round(10 ** rng.uniform(0.5, 6), 2)))
        net_revenue = compute_trade(units, sell, sell, buy_limit=False, sell_limit=True, broker_rate=rate, profile=p)
        revenue = net_revenue.sell_gross - net_revenue.sell_fee - net_revenue.sales_tax
        goal = D(str(round(rng.uniform(0, 0.5), 3)))
        b = targets.max_buy_price(units, revenue, broker_rate=rate, target_roi=goal)
        if b is None:
            continue
        at = compute_trade(units, b, sell, buy_limit=True, sell_limit=True, broker_rate=rate, profile=p)
        assert abs(at.roi - goal) < D("1e-12")


def test_max_units_is_the_largest_that_fits():
    rng = random.Random(8)
    for _ in range(3000):
        price = D(str(round(10 ** rng.uniform(0, 8), 2)))
        avail = D(str(round(10 ** rng.uniform(1, 11), 2)))
        rate = D("0.024")
        q = capital.max_units(avail, price, rate)
        if q:
            assert capital.cost_of_buy_order(D(q), price, rate) <= avail
        assert capital.cost_of_buy_order(D(q + 1), price, rate) > avail


def test_available_capital_never_negative_and_no_double_escrow():
    assert capital.available_capital(D("100"), D("30")) == D("70")
    assert capital.available_capital(D("100"), D("500")) == D("0")


def test_capital_block_in_assessment():
    a = ev(available_capital="50000")
    assert a.capital["affordable"] is False and a.capital["needed"] == D("102400.00")
    assert a.capital["max_units"] == 488       # 488 · 100 · 1,024 = 49 971,2 ≤ 50 000 < 489 · 102,4
    assert ev(available_capital="200000").capital["affordable"] is True


# ---- Escenarios ------------------------------------------------------------------------------------------------

def test_scenarios_are_independent_and_do_not_mutate_the_base():
    base = TradeInput(units=1000, buy_price="100", sell_price="125")
    out = run_scenarios(base, {"skills_v": {"profile": Profile(5, 5, 5)}, "sell_lower": {"sell_price": "110"}})
    assert set(out) == {"base", "skills_v", "sell_lower"}
    assert out["skills_v"].result["net_profit"] > out["base"].result["net_profit"] > out["sell_lower"].result["net_profit"]
    assert out["base"].result == evaluate(base).result and base.sell_price == "125"
    with pytest.raises(ValueError):
        run_scenarios(base, {"base": {}})


def test_determinism():
    assert ev().to_dict() == ev().to_dict()
    assert replace(TradeInput(units=5, buy_price="3", sell_price="9")).units == 5
    assert DEFAULT_RULES.min_order_fee == D("100")


# ---- Casos que las pruebas de mutación encontraron sin cubrir ------------------------------------------------

def test_sell_immediately_takes_the_best_bids_first():
    g = book.sell_immediate([(10, 3), (12, 2)], 2)
    assert g.total == D("24") and g.average_price == D("12") and g.levels_used == 1
    h = book.sell_immediate([(10, 3), (12, 2)], 4)
    assert h.total == D("44")                                   # 2 a 12 + 2 a 10


def test_advanced_broker_relations_raises_the_relist_discount():
    assert relist_discount(Profile(advanced_broker_relations=5)) == D("0.80")
    low = relist_fee(D("100"), D("110"), D("10000"), D("0.024"), Profile(advanced_broker_relations=0))
    high = relist_fee(D("100"), D("110"), D("10000"), D("0.024"), Profile(advanced_broker_relations=5))
    assert high < low and high == D("0.024") * 10 * 10000 + D("0.2") * D("0.024") * 110 * 10000
    assert relist_discount(Profile(advanced_broker_relations=5), replace(DEFAULT_RULES, relist_discount_base=D("0.9"))) == D("1")


def test_the_broker_fee_floor_binds_when_the_rule_set_raises_it():
    strict = replace(DEFAULT_RULES, npc_broker_floor=D("0.02"))
    assert broker_fee_rate(Profile(broker_relations=5), NPC, strict) == D("0.02")
    assert broker_fee_rate(Profile(broker_relations=5), NPC) == D("0.015")
