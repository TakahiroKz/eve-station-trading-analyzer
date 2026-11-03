import pytest

from domain.hard_stops import HardStopViolation
from domain.models import ThresholdConfig
from domain.recommendation_engine import RecommendationStatus, build_recommendation
from domain.risk_analyzer import Rating, RatingLevel
from domain.recommendation_engine import ExplainedFactor
from domain.score_engine import ScoreResult, ScoreSubfactors


def make_thresholds():
    return ThresholdConfig(
        trend_favorable_min=10.0, trend_neutral_min=0.0, trend_caution_min=-10.0,
        volatility_low_max=15.0, volatility_medium_max=35.0,
        spread_insufficient_max=7.0, spread_low_max=10.0, spread_good_max=20.0, spread_very_good_max=30.0,
        discrepancy_pct_threshold=5.0, score_buy_min=75.0, score_caution_min=60.0, score_watch_min=40.0,
    )


def make_score_result(total):
    subs = ScoreSubfactors(0, 0, 0, 0, 0, 0, 0, 0)
    return ScoreResult(total_score=total, subfactors=subs, weighted_breakdown={})


def test_hard_stop_forces_do_not_buy_even_with_perfect_score():
    score_result = make_score_result(100.0)
    violations = [HardStopViolation(code="X", message="critico")]
    factors = [ExplainedFactor("margen", Rating(RatingLevel.EXCELLENT, "bueno", "🟢"), "Margen neto atractivo")]
    rec = build_recommendation(score_result, violations, factors, make_thresholds())
    assert rec.status == RecommendationStatus.DO_NOT_BUY
    assert "critico" in rec.hard_stop_messages


def test_buy_when_score_high_and_no_risky_factors():
    score_result = make_score_result(90.0)
    factors = [ExplainedFactor("margen", Rating(RatingLevel.EXCELLENT, "bueno", "🟢"), "Margen neto atractivo")]
    rec = build_recommendation(score_result, [], factors, make_thresholds())
    assert rec.status == RecommendationStatus.BUY
    assert "Margen neto atractivo" in rec.reasons


def test_buy_with_caution_when_score_high_but_caution_factor_present():
    score_result = make_score_result(90.0)
    factors = [
        ExplainedFactor("margen", Rating(RatingLevel.EXCELLENT, "bueno", "🟢"), "Margen neto atractivo"),
        ExplainedFactor("volatilidad", Rating(RatingLevel.CAUTION, "media", "🟡"), "Volatilidad incrementa el riesgo"),
    ]
    rec = build_recommendation(score_result, [], factors, make_thresholds())
    assert rec.status == RecommendationStatus.BUY_WITH_CAUTION
    assert "Volatilidad incrementa el riesgo" in rec.risks


def test_watch_when_score_medium():
    score_result = make_score_result(50.0)
    rec = build_recommendation(score_result, [], [], make_thresholds())
    assert rec.status == RecommendationStatus.WATCH


def test_do_not_buy_when_score_low():
    score_result = make_score_result(10.0)
    rec = build_recommendation(score_result, [], [], make_thresholds())
    assert rec.status == RecommendationStatus.DO_NOT_BUY
