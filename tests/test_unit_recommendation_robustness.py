"""Robustez y veracidad del bloque `recommendation` del detalle: exactitud, límites, coherencia entre endpoints,
JSON estricto, determinismo y concurrencia."""
import json
import random
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from tests.test_capital_api import make_scored
from tests.test_unit_recommendation import prices

FEE_SELL, FEE_BUY = 0.901, 1.024


def reject_constants(name):
    raise ValueError(f"constante no estándar en el JSON: {name}")


def strict_json(response):
    return json.loads(response.text, parse_constant=reject_constants)


@pytest.fixture
def market(client):
    api_client, db_path = client
    make_scored(db_path, 34, "Fast mover", volume=50_000_000, stored_score=90)
    make_scored(db_path, 35, "Slow mover", volume=200_000, stored_score=40)
    make_scored(db_path, 36, "Cheap mover", volume=500_000_000, stored_score=60)
    prices(db_path, 34)
    prices(db_path, 35)
    prices(db_path, 36, buy=4.0, sell=4.85)               # spread 21,25 %: «Buen margen»
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE item_status SET roi = ? WHERE type_id = 36", (1.2125 * FEE_SELL / FEE_BUY - 1,))
    conn.commit()
    conn.close()
    return api_client, db_path


def test_the_net_profit_uses_the_exact_unit_profit_not_a_value_rounded_to_two_decimals(market):
    api_client, _ = market

    block = api_client.get("/api/items/36", params={"capital": 1_000_000_000}).json()["recommendation"]

    unit_profit = 4.85 * FEE_SELL - 4.0 * FEE_BUY         # 0,27385 ISK; redondeado a 2 decimales serían 0,27
    assert block["unidades_sugeridas"] == int(100_000_000 // (4.0 * FEE_BUY))
    assert block["beneficio_neto_isk"] == round(block["unidades_sugeridas"] * unit_profit)
    assert abs(block["beneficio_neto_isk"] - block["unidades_sugeridas"] * 0.27) > 50_000   # no es el redondeado


def test_an_item_without_daily_volume_has_no_recommendation_instead_of_failing(market):
    api_client, db_path = market
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE item_status SET volumen_diario_real = 0 WHERE type_id = 34")
    conn.commit()
    conn.close()

    response = api_client.get("/api/items/34", params={"capital": 50_000_000})

    assert response.status_code == 200 and response.json()["recommendation"] is None


def test_an_inverted_market_never_recommends_buying(market):
    api_client, db_path = market
    prices(db_path, 34, buy=1000.0, sell=800.0)

    block = api_client.get("/api/items/34").json()["recommendation"]

    assert block["unidades_sugeridas"] == 0 and block["inversion_isk"] == 0 and block["beneficio_neto_isk"] == 0
    assert block["action"] == "REJECT" and "NET_PROFIT_NOT_POSITIVE" in block["blocked_by"]


@pytest.mark.parametrize("buy,sell,capital", [
    (0.01, 0.02, 1e13), (0.01, 0.02, 1_000_000), (1e12, 1.3e12, 1e13), (1e12, 1.3e12, 1_000_000),
    (1.0, 1.0000001, 5e7), (123456789.123, 150000000.5, 987_654_321),
])
def test_extreme_prices_and_capitals_give_finite_consistent_numbers(market, buy, sell, capital):
    api_client, db_path = market
    prices(db_path, 34, buy=buy, sell=sell)

    response = api_client.get("/api/items/34", params={"capital": capital})
    block = strict_json(response)["recommendation"]

    assert response.status_code == 200
    assert block["unidades_sugeridas"] >= 0 and block["inversion_isk"] <= block["posicion_isk"]
    assert block["inversion_isk"] >= 0 and block["precio_unidad_isk"] >= 0
    assert (block["unidades_sugeridas"] > 0) == (block["alcanza"] and block["action"] != "REJECT"
                                                  and block["unidades_sugeridas"] > 0)


def test_every_response_is_strict_json_without_nan_or_infinity(market):
    api_client, db_path = market
    for buy, sell in ((1000.0, 1300.0), (1000.0, 900.0), (0.01, 0.5)):
        prices(db_path, 34, buy=buy, sell=sell)
        for capital in (None, 1_000_000, 50_000_000, 1e13):
            params = {} if capital is None else {"capital": capital}
            strict_json(api_client.get("/api/items/34", params=params))
            strict_json(api_client.get("/api/items", params={**params, "sort": "score"}))


def test_random_capitals_never_break_the_invariants(market):
    api_client, _ = market
    rng = random.Random(99)
    last_position = {}
    for _ in range(150):
        capital = 10 ** rng.uniform(6, 13)
        for type_id in (34, 35, 36):
            block = api_client.get(f"/api/items/{type_id}", params={"capital": capital}).json()["recommendation"]
            assert block["inversion_isk"] <= block["posicion_isk"]
            assert block["unidades_sugeridas"] >= 0
            assert block["position_pct"] == 0.1 and block["posicion_isk"] == round(block["capital"] * 0.1)
            assert block["capital"] >= 1_000_000
            if not block["alcanza"]:
                assert block["unidades_sugeridas"] == 0
            last_position[(type_id, block["capital"])] = block["posicion_isk"]


def test_the_recommendation_agrees_with_the_assessment_of_the_same_response(market):
    api_client, _ = market
    for type_id in (34, 35, 36):
        for capital in (None, 50_000_000, 5_000_000_000):
            params = {} if capital is None else {"capital": capital}
            body = api_client.get(f"/api/items/{type_id}", params=params).json()
            reco, assessment = body["recommendation"], body["assessment"]

            # Única diferencia permitida: «candidato a compra» con 0 unidades se muestra como «esperar».
            assert reco["action"] == assessment["recommendation"]["action"] or (
                reco["action"] == "WAIT" and assessment["recommendation"]["action"] == "BUY_CANDIDATE"
                and reco["unidades_sugeridas"] == 0)
            if reco["action"] == "REJECT":
                assert reco["blocked_by"] == assessment["eligibility"]["failed_filters"]
            else:
                assert reco["blocked_by"] == []
            assert reco["capital"] == assessment["score"]["reference"]["capital"]
            assert reco["posicion_isk"] == assessment["score"]["reference"]["position_isk"]


def test_list_and_detail_show_the_same_score_for_the_same_capital(market):
    api_client, _ = market
    for capital in (None, 50_000_000, 123_000_000, 5_000_000_000):
        params = {} if capital is None else {"capital": capital}
        listed = {i["type_id"]: i for i in api_client.get("/api/items", params={**params, "sort": "score"}).json()["items"]}
        for type_id, item in listed.items():
            detail = api_client.get(f"/api/items/{type_id}", params=params).json()["status"]

            assert detail["score"] == item["score"] and detail["eligibility"] == item["eligibility"]
            assert detail["recommendation"] == item["recommendation"]


def test_the_same_request_always_gives_the_same_answer_whatever_was_asked_before(market):
    api_client, _ = market
    first = api_client.get("/api/items/35", params={"capital": 50_000_000}).json()
    api_client.get("/api/items/35", params={"capital": 5_000_000_000})
    api_client.get("/api/items", params={"capital": 80_000_000, "sort": "score"})
    again = api_client.get("/api/items/35", params={"capital": 50_000_000}).json()

    assert first["recommendation"] == again["recommendation"] and first["assessment"] == again["assessment"]


def test_parallel_requests_get_the_same_answers_as_sequential_ones(market):
    _, db_path = market
    jobs = [(type_id, capital) for type_id in (34, 35, 36) for capital in (None, 50_000_000, 250_000_000, 5_000_000_000)]
    sequential_client = TestClient(app)
    expected = {job: sequential_client.get(f"/api/items/{job[0]}",
                                           params={} if job[1] is None else {"capital": job[1]}).json()["recommendation"]
                for job in jobs}

    def fetch(job):
        local = TestClient(app)                     # un cliente por hilo: el de Starlette no es seguro entre hilos
        response = local.get(f"/api/items/{job[0]}", params={} if job[1] is None else {"capital": job[1]})
        return job, response.status_code, response.json()["recommendation"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, jobs * 6))

    assert len(results) == len(jobs) * 6
    assert all(status == 200 for _, status, _ in results)
    assert all(block == expected[job] for job, _, block in results)


def test_a_buy_candidate_is_never_shown_with_zero_units(market):
    api_client, db_path = market
    prices(db_path, 34, buy=1000.0, sell=1140.0)          # spread 14 %: el motor de unidades dice «no ejecutar»
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE item_status SET roi = 0.5 WHERE type_id = 34")   # ...pero el puntaje lo daba por bueno
    conn.commit()
    conn.close()

    body = api_client.get("/api/items/34").json()

    assert body["assessment"]["recommendation"]["action"] == "BUY_CANDIDATE"
    assert body["recommendation"]["unidades_sugeridas"] == 0 and body["recommendation"]["action"] == "WAIT"
    assert body["recommendation"]["recomendacion"].startswith("No ejecutar el trade")


def test_rotation_days_use_the_seven_day_volume_not_the_thirty_day_average(market):
    api_client, db_path = market
    conn = sqlite3.connect(db_path)       # el volumen de los últimos 7 días es la mitad del de 30 días
    conn.execute("UPDATE item_status SET avg_daily_volume_7d = 25_000_000, volumen_diario_real = 50_000_000 "
                 "WHERE type_id = 34")
    conn.commit()
    conn.close()

    block = api_client.get("/api/items/34", params={"capital": 5_000_000_000}).json()["recommendation"]

    units = block["unidades_sugeridas"]
    assert units > 0
    assert block["dias_rotacion"] == pytest.approx(units / (25_000_000 * 0.1), abs=0.006)
    assert block["dias_rotacion"] != pytest.approx(units / (50_000_000 * 0.1), abs=0.006)


def test_the_filtered_list_is_computed_per_capital_and_never_reuses_another_capitals_scores(market):
    api_client, _ = market

    def names(capital):
        body = api_client.get("/api/items", params={"capital": capital, "min_score": 55, "limit": 50}).json()
        return {i["name"]: i["score"] for i in body["items"]}

    small = names(50_000_000)
    huge = names(5_000_000_000_000)
    small_again = names(50_000_000)

    assert small == small_again
    assert small != huge                            # con un capital enorme la posición no cabe en el mercado lento
    assert small.get("Slow mover", 0) > huge.get("Slow mover", 0)
