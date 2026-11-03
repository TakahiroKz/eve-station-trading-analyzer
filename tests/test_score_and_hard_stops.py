import pytest

from domain.hard_stops import HardStopInputs, evaluate_hard_stops
from domain.models import HardStopConfig, ScoreWeights
from domain.risk_analyzer import RatingLevel
from domain.score_engine import ScoreSubfactors, calculate_viability_score


def make_weights():
    return ScoreWeights(
        net_margin=25, profit_unit=10, liquidity=20, profit_day=15,
        trend=10, volatility=10, capital_efficiency=5, market_depth=5,
    )


def test_score_all_perfect_is_100():
    subs = ScoreSubfactors(100, 100, 100, 100, 100, 100, 100, 100)
    result = calculate_viability_score(subs, make_weights())
    assert result.total_score == pytest.approx(100.0)


def test_score_all_zero_is_0():
    subs = ScoreSubfactors(0, 0, 0, 0, 0, 0, 0, 0)
    result = calculate_viability_score(subs, make_weights())
    assert result.total_score == pytest.approx(0.0)


def test_high_margin_alone_does_not_dominate_score():
    """Regla fundamental: mayor margin no debe implicar automaticamente mejor score."""
    subs = ScoreSubfactors(
        net_margin_score=100, profit_unit_score=0, liquidity_score=0, profit_day_score=0,
        trend_score=0, volatility_score=0, capital_efficiency_score=0, market_depth_score=0,
    )
    result = calculate_viability_score(subs, make_weights())
    assert result.total_score < 30  # el peso del margen es solo 25%


def make_hard_stop_config():
    return HardStopConfig(
        trend_min_pct=-20.0, volatility_max_pct=50.0, net_margin_min_pct=5.0,
        liquidity_insufficient_blocks=True,
    )


def test_hard_stop_blocks_on_bad_trend():
    inputs = HardStopInputs(
        trend_pct=-25.0, volatility_pct=10.0, net_margin_pct=20.0,
        position_exceeds_capital=False, liquidity_level=RatingLevel.EXCELLENT,
    )
    violations = evaluate_hard_stops(inputs, make_hard_stop_config())
    assert any(v.code == "TREND_TOO_NEGATIVE" for v in violations)


def test_hard_stop_none_when_all_good():
    inputs = HardStopInputs(
        trend_pct=10.0, volatility_pct=10.0, net_margin_pct=20.0,
        position_exceeds_capital=False, liquidity_level=RatingLevel.EXCELLENT,
    )
    violations = evaluate_hard_stops(inputs, make_hard_stop_config())
    assert violations == []


def test_hard_stop_high_score_cannot_hide_critical_condition():
    """Un producto no puede obtener score alto y aun asi recomendarse si hay hard stop."""
    subs = ScoreSubfactors(100, 100, 100, 100, 100, 100, 100, 100)
    score_result = calculate_viability_score(subs, make_weights())
    assert score_result.total_score == pytest.approx(100.0)

    inputs = HardStopInputs(
        trend_pct=-25.0, volatility_pct=10.0, net_margin_pct=20.0,
        position_exceeds_capital=False, liquidity_level=RatingLevel.EXCELLENT,
    )
    violations = evaluate_hard_stops(inputs, make_hard_stop_config())
    assert len(violations) > 0
