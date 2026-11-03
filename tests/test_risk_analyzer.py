from domain.models import ThresholdConfig
from domain.risk_analyzer import (
    RatingLevel,
    classify_liquidity,
    classify_market_depth,
    classify_spread,
    classify_trend,
    classify_volatility,
)


def make_thresholds():
    return ThresholdConfig(
        trend_favorable_min=10.0,
        trend_neutral_min=0.0,
        trend_caution_min=-10.0,
        volatility_low_max=15.0,
        volatility_medium_max=35.0,
        spread_insufficient_max=7.0,
        spread_low_max=10.0,
        spread_good_max=20.0,
        spread_very_good_max=30.0,
        discrepancy_pct_threshold=5.0,
        score_buy_min=75.0,
        score_caution_min=60.0,
        score_watch_min=40.0,
    )


def test_classify_trend_levels():
    t = make_thresholds()
    assert classify_trend(26.2, t).level == RatingLevel.EXCELLENT
    assert classify_trend(5.0, t).level == RatingLevel.GOOD
    assert classify_trend(-5.0, t).level == RatingLevel.CAUTION
    assert classify_trend(-25.0, t).level == RatingLevel.BAD


def test_classify_volatility_levels():
    t = make_thresholds()
    assert classify_volatility(10.0, t).level == RatingLevel.EXCELLENT
    assert classify_volatility(20.0, t).level == RatingLevel.CAUTION
    assert classify_volatility(50.0, t).level == RatingLevel.BAD


def test_classify_spread_very_high_is_not_automatically_excellent():
    t = make_thresholds()
    assert classify_spread(42.97, t).level == RatingLevel.CAUTION
    assert classify_spread(15.0, t).level == RatingLevel.EXCELLENT
    assert classify_spread(3.0, t).level == RatingLevel.BAD


def test_classify_liquidity_uses_depth_not_only_volume():
    high = classify_liquidity(volume_day=390, buy_depth=1253, sell_depth=460)
    assert high.level == RatingLevel.EXCELLENT
    low_depth = classify_liquidity(volume_day=390, buy_depth=1253, sell_depth=10)
    assert low_depth.level != RatingLevel.EXCELLENT


def test_classify_market_depth():
    good = classify_market_depth(units_ahead=37, volume_day=390)
    assert good.level == RatingLevel.EXCELLENT
