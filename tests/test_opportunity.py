"""Filtros duros, elegibilidad, recomendación y explicación (analytics/opportunity.py)."""
import pytest

from analytics.opportunity import (
    OpportunityConfig,
    OpportunityContext,
    assess_opportunity,
    evaluate_item,
    inputs_blob,
    parse_inputs_blob,
)
from analytics.scoring import ScoreConfig, ScoreInputs, score_opportunity
from storage.settings_registry import SETTINGS


def make_inputs(**changes) -> ScoreInputs:
    base = dict(roi=0.30, best_buy=1000.0, volume_7d=5_000_000.0, volume_30d=5_000_000.0, ops_7d=120.0,
                buy_orders=40, sell_orders=40, status="POTENCIAL", price_cv=0.03)
    base.update(changes)
    return ScoreInputs(**base)


def make_context(**changes) -> OpportunityContext:
    base = dict(unit_profit=250.0, price_sane=True, data_age_min=2.0)
    base.update(changes)
    return OpportunityContext(**base)


def assess(item=None, ctx=None, **config):
    item = item or make_inputs()
    score = score_opportunity(item, ScoreConfig())
    return assess_opportunity(item, ctx or make_context(), score, ScoreConfig(), OpportunityConfig(**config))


def test_a_strong_profitable_item_is_recommended_as_a_buy_candidate():
    result = assess()

    assert result["eligibility"]["status"] == "RECOMMENDED"
    assert result["eligibility"]["failed_filters"] == []
    assert result["recommendation"]["action"] == "BUY_CANDIDATE"
    assert {"SCORE_ABOVE_MINIMUM", "ROI_ABOVE_MINIMUM", "LIQUIDITY_ABOVE_MINIMUM", "HOLDING_TIME_OK"} <= set(
        result["recommendation"]["reason_codes"])
    assert result["recommendation"]["to_change"] == []


def test_qa03_a_negative_net_profit_is_rejected_and_never_a_buy_candidate():
    result = assess(ctx=make_context(unit_profit=-5.0))

    assert result["eligibility"]["status"] == "NO_ELIGIBLE"
    assert "NET_PROFIT_NOT_POSITIVE" in result["eligibility"]["failed_filters"]
    assert result["recommendation"]["action"] == "REJECT"


@pytest.mark.parametrize("changes", [dict(buy_orders=0), dict(sell_orders=0), dict(best_buy=0.0)])
def test_qa01_qa02_an_item_without_valid_orders_is_not_eligible(changes):
    result = assess(item=make_inputs(**changes))

    assert result["eligibility"]["status"] == "NO_ELIGIBLE"
    assert "NO_VALID_ORDERS" in result["eligibility"]["failed_filters"]
    assert result["recommendation"]["action"] == "REJECT"


def test_qa05_stale_data_means_wait_even_if_everything_else_is_fine():
    result = assess(ctx=make_context(data_age_min=45.0))

    assert result["eligibility"]["status"] == "NO_ELIGIBLE"
    assert "STALE_MARKET_DATA" in result["eligibility"]["failed_filters"]
    assert result["recommendation"]["action"] == "WAIT"
    changes = result["recommendation"]["to_change"]
    assert any(c["code"] == "STALE_MARKET_DATA" and c["needed"] == 30.0 for c in changes)


def test_qa06_a_volume_below_the_minimum_is_not_eligible():
    result = assess(item=make_inputs(volume_7d=3.0), min_daily_volume_7d=10)

    assert "VOLUME_BELOW_MINIMUM" in result["eligibility"]["failed_filters"]
    assert result["eligibility"]["status"] == "NO_ELIGIBLE"


def test_a_zero_volume_minimum_disables_that_filter():
    result = assess(item=make_inputs(volume_7d=3.0), min_daily_volume_7d=0)

    assert "VOLUME_BELOW_MINIMUM" not in result["eligibility"]["failed_filters"]


def test_qa08_an_excessively_volatile_item_is_not_eligible_for_its_risk():
    result = assess(item=make_inputs(price_cv=0.9, volume_7d=15_000_000.0))  # precio inestable y volumen disparado

    assert "HIGH_VOLATILITY" in result["eligibility"]["failed_filters"]
    assert result["recommendation"]["action"] == "REJECT"


def test_qa04_a_roi_below_the_minimum_is_eligible_but_not_recommended_and_says_what_to_change():
    result = assess(item=make_inputs(roi=0.03), ctx=make_context(unit_profit=30.0))

    assert result["eligibility"]["status"] == "ELIGIBLE"
    assert result["recommendation"]["action"] == "WAIT"
    assert "ROI_BELOW_MINIMUM" in result["recommendation"]["reason_codes"]
    change = next(c for c in result["recommendation"]["to_change"] if c["code"] == "ROI_BELOW_MINIMUM")
    assert change["current"] == 0.03 and change["needed"] == 0.05


def test_qa14_a_position_that_takes_too_long_to_sell_is_not_recommended():
    quick = assess(item=make_inputs(volume_7d=1_000_000.0, volume_30d=1_000_000.0))  # 100k / 100k capturables = 1 día
    slow = assess(item=make_inputs(volume_7d=40_000.0, volume_30d=40_000.0))      # 25 días

    assert quick["recommendation"]["action"] == "BUY_CANDIDATE"
    assert slow["recommendation"]["action"] == "WAIT"
    assert "EXCESSIVE_HOLDING_TIME" in slow["recommendation"]["reason_codes"]


def test_a_discarded_status_or_an_inconsistent_price_can_never_be_eligible_despite_a_high_score():
    discarded = assess(item=make_inputs(status="DESCARTADO"))
    insane = assess(ctx=make_context(price_sane=False))

    assert "CLASSIFIED_DISCARDED" in discarded["eligibility"]["failed_filters"]
    assert "PRICE_INCONSISTENT" in insane["eligibility"]["failed_filters"]
    assert discarded["recommendation"]["action"] == insane["recommendation"]["action"] == "REJECT"


def test_the_reference_block_exposes_the_position_used_for_the_evaluation():
    ref = assess()["reference"]

    assert ref["position_isk"] == 100_000_000 and ref["quantity"] == 100_000
    assert ref["holding_days"] == pytest.approx(0.2, abs=0.01) and ref["net_profit"] == 25_000_000


def test_evaluate_item_is_deterministic_and_driven_by_the_settings_registry():
    settings = {s.key: s.default_value for s in SETTINGS}
    extras = {"cv": 0.03, "age": 2.0, "sane": True}

    first = evaluate_item(make_inputs(), 1300.0, extras, settings)
    second = evaluate_item(make_inputs(), 1300.0, extras, settings)
    assert first[0].to_dict() == second[0].to_dict() and first[1] == second[1]
    assert first[1]["eligibility"]["status"] == "RECOMMENDED"

    strict = evaluate_item(make_inputs(), 1300.0, extras, {**settings, "min_opportunity_score": 100.0})
    assert strict[1]["eligibility"]["status"] == "ELIGIBLE" and strict[0].version == first[0].version


def test_changing_a_scoring_setting_gives_a_new_version():
    settings = {s.key: s.default_value for s in SETTINGS}
    extras = {"cv": 0.03, "age": 2.0, "sane": True}

    old = evaluate_item(make_inputs(), 1300.0, extras, settings)[0]
    new = evaluate_item(make_inputs(), 1300.0, extras, {**settings, "score_w_volume": 0.30})[0]

    assert old.version != new.version


def test_inputs_blob_round_trips_and_tolerates_garbage():
    blob = inputs_blob(0.123456, 3.14159, False)

    assert parse_inputs_blob(blob) == {"cv": 0.1235, "age": 3.1, "sane": False}
    assert parse_inputs_blob(None) == {"cv": None, "age": None, "sane": True}
    assert parse_inputs_blob("{no es json") == {"cv": None, "age": None, "sane": True}
