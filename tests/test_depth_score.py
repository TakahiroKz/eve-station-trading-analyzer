"""La profundidad del libro en el puntaje (algoritmo 1.1.0): factor «libro y actividad» y filtro duro."""
import json
import sqlite3

import pytest

from analytics.opportunity import (
    OpportunityConfig,
    OpportunityContext,
    assess_opportunity,
    evaluate_item,
    inputs_blob,
    parse_inputs_blob,
)
from analytics.scoring import ScoreConfig, ScoreInputs, depth_ratio, score_opportunity
from storage.settings_registry import SETTINGS
from tests.conftest import seed_item


def make_inputs(**changes) -> ScoreInputs:
    # posición de referencia = 100 M ISK / 1000 = 100.000 unidades
    base = dict(roi=0.30, best_buy=1000.0, volume_7d=5_000_000.0, volume_30d=5_000_000.0, ops_7d=120.0,
                buy_orders=40, sell_orders=40, status="POTENCIAL", price_cv=0.03,
                buy_depth=500_000, sell_depth=400_000)
    base.update(changes)
    return ScoreInputs(**base)


def book(result):
    return next(f for f in result.factors if f.key == "book")


def test_depth_ratio_uses_the_shallower_side_over_the_reference_quantity():
    assert depth_ratio(make_inputs(buy_depth=500_000, sell_depth=40_000), 100_000) == pytest.approx(0.4)
    assert depth_ratio(make_inputs(buy_depth=None), 100_000) is None
    assert depth_ratio(make_inputs(sell_depth=None), 100_000) is None
    assert depth_ratio(make_inputs(), 0) is None


def test_a_deep_book_scores_higher_than_a_shallow_one_with_the_same_activity():
    deep = book(score_opportunity(make_inputs(buy_depth=500_000, sell_depth=400_000)))
    shallow = book(score_opportunity(make_inputs(buy_depth=2_000, sell_depth=400_000)))

    assert deep.score > shallow.score
    assert deep.code == "BOOK_ACTIVE" and shallow.code == "BOOK_SHALLOW"
    assert deep.metrics["depth_ratio"] == pytest.approx(4.0) and shallow.metrics["depth_ratio"] == pytest.approx(0.02)
    assert "profundidad" in deep.value


def test_without_depth_data_the_book_factor_is_the_activity_only_as_before():
    with_data = book(score_opportunity(make_inputs(buy_depth=10**9, sell_depth=10**9)))
    without = book(score_opportunity(make_inputs(buy_depth=None, sell_depth=None)))

    assert without.metrics["depth_ratio"] is None and without.code == "BOOK_ACTIVE"
    assert "profundidad" not in without.value
    assert without.score == pytest.approx(100.0)       # 120 operaciones/día: la curva de actividad da 100
    assert with_data.score == pytest.approx(100.0)     # actividad 100 y profundidad >= 3x: 100


def test_a_thin_book_note_wins_over_the_shallow_note():
    result = book(score_opportunity(make_inputs(buy_orders=1, buy_depth=10, sell_depth=10)))

    assert result.code == "BOOK_THIN"


def assess(item, **config):
    score = score_opportunity(item, ScoreConfig())
    return assess_opportunity(item, OpportunityContext(250.0, True, 2.0), score, ScoreConfig(),
                              OpportunityConfig(**config))


def test_an_insufficient_depth_makes_the_item_not_eligible_whatever_its_score():
    result = assess(make_inputs(buy_depth=500_000, sell_depth=5_000))  # 5 % de la posición

    assert "INSUFFICIENT_DEPTH" in result["eligibility"]["failed_filters"]
    assert result["eligibility"]["status"] == "NO_ELIGIBLE" and result["recommendation"]["action"] == "REJECT"
    change = next(c for c in result["recommendation"]["to_change"] if c["code"] == "INSUFFICIENT_DEPTH")
    assert change["current"] == pytest.approx(0.05) and change["needed"] == 0.10


def test_a_deep_enough_book_passes_and_a_zero_minimum_disables_the_filter():
    assert assess(make_inputs())["eligibility"]["status"] == "RECOMMENDED"

    off = assess(make_inputs(buy_depth=10, sell_depth=10), min_depth_ratio=0)
    assert "INSUFFICIENT_DEPTH" not in off["eligibility"]["failed_filters"]


def test_without_depth_data_the_filter_cannot_be_applied_and_does_not_block():
    result = assess(make_inputs(buy_depth=None, sell_depth=None))

    assert "INSUFFICIENT_DEPTH" not in result["eligibility"]["failed_filters"]
    assert result["eligibility"]["status"] == "RECOMMENDED"


def test_the_inputs_blob_carries_the_depth_and_old_blobs_still_parse():
    blob = inputs_blob(0.03, 2.0, True, 1200, 800)

    assert parse_inputs_blob(blob) == {"cv": 0.03, "age": 2.0, "sane": True, "bd": 1200, "sd": 800}
    assert parse_inputs_blob('{"cv":0.1,"age":1.0,"sane":true}')["bd"] is None  # guardado antes de la 1.1.0


def test_evaluate_item_is_driven_by_the_registry_default_for_the_depth_minimum():
    settings = {s.key: s.default_value for s in SETTINGS}
    assert settings["min_depth_ratio"] == 0.10

    shallow = ScoreInputs(**{**make_inputs().__dict__, "sell_depth": 1_000})
    score, assessment = evaluate_item(shallow, 1300.0, {"cv": 0.03, "age": 2.0, "sane": True}, settings)
    assert "INSUFFICIENT_DEPTH" in assessment["eligibility"]["failed_filters"]
    lenient = evaluate_item(shallow, 1300.0, {"cv": 0.03, "age": 2.0, "sane": True}, {**settings, "min_depth_ratio": 0})[1]
    assert "INSUFFICIENT_DEPTH" not in lenient["eligibility"]["failed_filters"]
    assert score.version.startswith("1.1.0-")


def test_the_item_detail_recomputes_the_depth_from_the_stored_inputs(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE item_status SET score = 80, score_class = 'HIGH', eligibility = 'NO_ELIGIBLE', "
        "recommendation = 'REJECT', score_version = '1.1.0-abc123', score_inputs = ?, "
        "avg_daily_volume_7d = 5000000, volumen_diario_real = 5000000, avg_daily_order_count_7d = 120, "
        "buy_order_count = 40, sell_order_count = 40, best_buy = 1000, best_sell = 1300, roi = 0.3 WHERE type_id = 34",
        (json.dumps({"cv": 0.03, "age": 2.0, "sane": True, "bd": 500000, "sd": 2000}),),
    )
    conn.commit()
    conn.close()

    assessment = api_client.get("/api/items/34").json()["assessment"]
    factor = next(f for f in assessment["score"]["factors"] if f["key"] == "book")

    assert factor["code"] == "BOOK_SHALLOW" and factor["metrics"]["depth_ratio"] == pytest.approx(0.02)
    assert "INSUFFICIENT_DEPTH" in assessment["eligibility"]["failed_filters"]
