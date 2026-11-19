"""El puntaje en la API pública: columnas del listado, filtros, orden y explicación del detalle."""
import json
import sqlite3

from tests.conftest import seed_item


def score_item(db_path, type_id, score, score_class, eligibility, recommendation, version="1.0.0-abc123"):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE item_status SET score = ?, score_class = ?, eligibility = ?, recommendation = ?, "
        "score_version = ?, score_inputs = ?, avg_daily_volume_7d = 5000000, volumen_diario_real = 5000000, "
        "avg_daily_order_count_7d = 120, buy_order_count = 40, sell_order_count = 40, "
        "best_buy = 1000, best_sell = 1300, roi = 0.3 WHERE type_id = ?",
        (score, score_class, eligibility, recommendation, version,
         json.dumps({"cv": 0.03, "age": 2.0, "sane": True}), type_id),
    )
    conn.commit()
    conn.close()


def seed_scored(db_path):
    seed_item(db_path, type_id=34, name="Tritanium")
    seed_item(db_path, type_id=35, name="Pyerite")
    seed_item(db_path, type_id=36, name="Mexallon")  # sin puntaje todavía
    score_item(db_path, 34, 91, "EXCELLENT", "RECOMMENDED", "BUY_CANDIDATE")
    score_item(db_path, 35, 40, "DISCARDED", "NO_ELIGIBLE", "REJECT")


def test_the_listing_carries_the_score_fields(client):
    api_client, db_path = client
    seed_scored(db_path)

    items = {i["name"]: i for i in api_client.get("/api/items").json()["items"]}

    assert items["Tritanium"]["score"] == 91 and items["Tritanium"]["score_class"] == "EXCELLENT"
    assert items["Tritanium"]["eligibility"] == "RECOMMENDED"
    assert items["Tritanium"]["recommendation"] == "BUY_CANDIDATE"
    assert items["Mexallon"]["score"] is None and items["Mexallon"]["eligibility"] is None


def test_items_can_be_sorted_by_score_with_unscored_items_always_last(client):
    api_client, db_path = client
    seed_scored(db_path)

    desc = [i["name"] for i in api_client.get("/api/items", params={"sort": "score", "order": "desc"}).json()["items"]]
    asc = [i["name"] for i in api_client.get("/api/items", params={"sort": "score", "order": "asc"}).json()["items"]]

    assert desc == ["Tritanium", "Pyerite", "Mexallon"]
    assert asc == ["Pyerite", "Tritanium", "Mexallon"]


def test_items_can_be_filtered_by_score_class_eligibility_and_recommendation(client):
    api_client, db_path = client
    seed_scored(db_path)

    def names(**params):
        return [i["name"] for i in api_client.get("/api/items", params=params).json()["items"]]

    assert names(min_score=50) == ["Tritanium"]
    assert names(score_class="DISCARDED") == ["Pyerite"]
    assert names(eligibility="RECOMMENDED") == ["Tritanium"]
    assert names(recommendation="REJECT") == ["Pyerite"]


def test_the_score_filters_reject_unknown_values(client):
    api_client, _ = client

    for params in ({"score_class": "GREAT"}, {"eligibility": "MAYBE"}, {"recommendation": "SELL_NOW"}, {"min_score": 101}):
        assert api_client.get("/api/items", params=params).status_code in (400, 422)


def test_the_detail_returns_the_full_explanation_of_the_score(client):
    api_client, db_path = client
    seed_scored(db_path)

    body = api_client.get("/api/items/34").json()
    assessment = body["assessment"]

    assert body["status"]["score"] == 91
    assert assessment["stored_version"] == "1.0.0-abc123"
    assert assessment["algorithm_version"].startswith("1.0.0-")
    assert assessment["config_changed"] is True  # la versión guardada es de mentira: no coincide con la actual
    factors = assessment["score"]["factors"]
    assert [f["key"] for f in factors] == ["profitability", "liquidity", "volume", "book", "stability", "capital"]
    assert all({"points", "max", "score", "value", "note"} <= set(f) for f in factors)
    assert sum(f["max"] for f in factors) == 100
    assert assessment["eligibility"]["status"] in {"RECOMMENDED", "ELIGIBLE", "NO_ELIGIBLE"}
    assert assessment["recommendation"]["action"] in {"BUY_CANDIDATE", "WAIT", "REJECT"}
    assert "reference" in assessment


def test_the_detail_has_no_assessment_until_the_item_is_scored(client):
    api_client, db_path = client
    seed_scored(db_path)

    assert api_client.get("/api/items/36").json()["assessment"] is None


def drop_score_columns(db_path):
    """Deja la tabla como estaba antes de la migración del puntaje (la API arranca antes que el motor)."""
    conn = sqlite3.connect(db_path)
    for column in ("score", "score_class", "eligibility", "recommendation", "score_version", "score_inputs"):
        conn.execute(f"ALTER TABLE item_status DROP COLUMN {column}")
    conn.commit()
    conn.close()


def test_the_detail_still_works_before_the_score_migration_has_run(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    drop_score_columns(db_path)

    response = api_client.get("/api/items/34")

    assert response.status_code == 200
    assert response.json()["assessment"] is None


def test_the_api_migrates_the_schema_when_it_starts(client):
    from fastapi.testclient import TestClient

    from backend.api.main import app

    _, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    drop_score_columns(db_path)

    with TestClient(app) as started:  # el contexto ejecuta el arranque (lifespan)
        assert started.get("/api/items", params={"sort": "score"}).status_code == 200

    conn = sqlite3.connect(db_path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(item_status)")}
    conn.close()
    assert {"score", "score_class", "eligibility", "recommendation", "score_version", "score_inputs"} <= columns
