"""Puntaje 0-100 explicable (analytics/scoring.py): factores, topes, pesos y reproducibilidad."""
import pytest

from analytics.scoring import (
    WEIGHT_KEYS,
    ScoreConfig,
    ScoreInputs,
    classification_for,
    config_version,
    holding_days,
    interp,
    normalized_weights,
    reference_position,
    score_opportunity,
    validate_weights,
)


def strong(**changes) -> ScoreInputs:
    base = dict(roi=0.30, best_buy=1000.0, volume_7d=5_000_000.0, volume_30d=5_000_000.0, ops_7d=120.0,
                buy_orders=40, sell_orders=40, status="POTENCIAL", price_cv=0.03)
    base.update(changes)
    return ScoreInputs(**base)


def factor(result, key):
    return next(f for f in result.factors if f.key == key)


def test_interp_follows_the_curve_and_clamps_outside_it():
    curve = [(0, 0), (10, 100)]
    assert interp(-5, curve) == 0
    assert interp(5, curve) == 50
    assert interp(99, curve) == 100


def test_the_total_is_the_sum_of_the_factor_points_and_each_factor_respects_its_maximum():
    result = score_opportunity(strong())

    assert result.total == pytest.approx(sum(f.points for f in result.factors))
    assert sum(f.max for f in result.factors) == pytest.approx(100)
    assert all(0 <= f.points <= f.max + 1e-9 for f in result.factors)
    assert [f.key for f in result.factors] == list(WEIGHT_KEYS)
    assert result.score == round(result.total)
    assert result.total > 80 and result.classification in {"HIGH", "EXCELLENT"}


def test_a_sustainable_roi_scores_above_a_thin_margin_and_above_an_absurd_one():
    sustainable = score_opportunity(strong(roi=0.30)).total
    thin = score_opportunity(strong(roi=0.06)).total
    absurd = score_opportunity(strong(roi=2.5, status="EN_OBSERVACION")).total

    assert sustainable > thin
    assert sustainable > absurd


def test_an_atypical_roi_is_capped_below_the_moderate_band_and_says_why():
    result = score_opportunity(strong(roi=1.8))

    assert result.total == 64
    assert result.classification == "LOW"
    assert [c["code"] for c in result.caps] == ["ATYPICAL_ROI"]


def test_a_discarded_item_never_scores_above_the_discarded_cap():
    result = score_opportunity(strong(status="DESCARTADO"))

    assert result.total == 29
    assert result.classification == "DISCARDED"
    assert result.caps[0]["code"] == "CLASSIFIED_DISCARDED"


def test_a_thin_book_halves_the_book_factor():
    healthy = score_opportunity(strong(buy_orders=40, sell_orders=40))
    thin = score_opportunity(strong(buy_orders=1, sell_orders=40))

    assert factor(thin, "book").score == pytest.approx(factor(healthy, "book").score / 2)
    assert "fino" in factor(thin, "book").note


def test_without_price_or_volume_data_there_is_no_score():
    for bad in (strong(best_buy=0), strong(volume_30d=0)):
        result = score_opportunity(bad)
        assert result.total is None and result.score is None
        assert result.caps[0]["code"] == "INSUFFICIENT_DATA"


def test_a_missing_volatility_is_neutral_and_explained():
    result = score_opportunity(strong(price_cv=None))

    assert "neutra" in factor(result, "stability").note


def test_a_position_that_the_market_cannot_absorb_loses_liquidity_points():
    liquid = score_opportunity(strong(volume_7d=5_000_000, volume_30d=5_000_000))
    illiquid = score_opportunity(strong(volume_7d=5_000, volume_30d=5_000))

    assert factor(liquid, "liquidity").score > 90
    assert factor(illiquid, "liquidity").score == 0


def test_the_same_inputs_and_configuration_give_the_same_result():
    assert score_opportunity(strong()).to_dict() == score_opportunity(strong()).to_dict()


def test_weights_are_normalized_and_invalid_weights_fall_back_to_the_defaults():
    doubled = ScoreConfig(score_w_profitability=0.5)  # suma 1,25
    weights = normalized_weights(doubled)
    assert sum(weights.values()) == pytest.approx(1)
    assert weights["profitability"] == pytest.approx(0.5 / 1.25)

    broken = ScoreConfig(score_w_liquidity=-1)
    assert normalized_weights(broken) == normalized_weights(ScoreConfig())
    zero = ScoreConfig(**{attr: 0 for attr in WEIGHT_KEYS.values()})
    assert normalized_weights(zero) == normalized_weights(ScoreConfig())


def test_validate_weights_rejects_out_of_range_and_bad_sums():
    good = {attr: getattr(ScoreConfig(), attr) for attr in WEIGHT_KEYS.values()}
    assert validate_weights(good) is None
    assert "entre 0 y 1" in validate_weights({**good, "score_w_volume": 1.5})
    assert "sumar 1" in validate_weights({**good, "score_w_volume": 0.5})
    assert validate_weights({"score_w_volume": 0.5}) is None  # un peso suelto solo se acota


def test_the_config_version_changes_when_a_weight_changes():
    assert config_version(ScoreConfig()) == config_version(ScoreConfig())
    assert config_version(ScoreConfig()) != config_version(ScoreConfig(score_w_volume=0.2))
    assert config_version(ScoreConfig()).startswith("1.1.0-")


def test_the_classification_bands_follow_the_spec():
    values = (100, 90, 89.9, 80, 79.9, 65, 64.9, 50, 49.9, 0)
    assert [classification_for(v) for v in values] == [
        "EXCELLENT", "EXCELLENT", "HIGH", "HIGH", "MODERATE", "MODERATE", "LOW", "LOW", "DISCARDED", "DISCARDED"]


def test_reference_position_and_holding_days_use_the_configured_capture_rate():
    config = ScoreConfig(score_reference_capital=1e9, position_size_pct_wallet=0.1, capture_participation_rate=0.1)
    ref = reference_position(config, 1000.0)
    assert ref["position_isk"] == pytest.approx(1e8) and ref["quantity"] == pytest.approx(100_000)
    assert holding_days(100_000, 50_000, config) == pytest.approx(20)  # 100k / (50k x 10 %)
    assert holding_days(100_000, 0, config) is None
