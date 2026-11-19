"""El puntaje con el capital del visitante (?capital=): recalcula solo lo que depende del capital."""
import json
import sqlite3

import pytest

from tests.conftest import seed_item


def make_scored(db_path, type_id, name, volume, stored_score, depth=(10**9, 10**9)):
    seed_item(db_path, type_id=type_id, name=name)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE item_status SET score = ?, score_class = 'LOW', eligibility = 'ELIGIBLE', recommendation = 'WAIT', "
        "score_version = '1.1.0-stored', score_inputs = ?, avg_daily_volume_7d = ?, volumen_diario_real = ?, "
        "avg_daily_order_count_7d = 120, buy_order_count = 40, sell_order_count = 40, best_buy = 1000, "
        "best_sell = 1300, roi = 0.3 WHERE type_id = ?",
        (stored_score, json.dumps({"cv": 0.03, "age": 1.0, "sane": True, "bd": depth[0], "sd": depth[1]}),
         volume, volume, type_id),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def seeded(client):
    api_client, db_path = client
    make_scored(db_path, 34, "Slow mover", volume=200_000, stored_score=10)   # a 1.000 M ISK la posición no cabe
    make_scored(db_path, 35, "Fast mover", volume=50_000_000, stored_score=95)
    return api_client


def names(response):
    return [i["name"] for i in response.json()["items"]]


def by_name(response):
    return {i["name"]: i for i in response.json()["items"]}


def test_without_capital_the_stored_score_is_returned_as_is(seeded):
    body = seeded.get("/api/items").json()

    assert body["capital"] is None
    assert {i["name"]: i["score"] for i in body["items"]} == {"Slow mover": 10, "Fast mover": 95}


def test_a_smaller_capital_raises_the_score_of_an_item_the_reference_position_could_not_sell(seeded):
    stored = by_name(seeded.get("/api/items"))["Slow mover"]["score"]
    small = seeded.get("/api/items", params={"capital": 50_000_000})
    big = seeded.get("/api/items", params={"capital": 5_000_000_000_000})

    assert small.json()["capital"] == 50_000_000
    assert by_name(small)["Slow mover"]["score"] > stored
    assert by_name(big)["Slow mover"]["score"] < by_name(small)["Slow mover"]["score"]


def test_the_score_filter_uses_the_recomputed_score_not_the_stored_one(seeded):
    # El puntaje guardado de «Slow mover» es 10; con 50 M de capital el recalculado supera 60.
    assert names(seeded.get("/api/items", params={"min_score": 60})) == ["Fast mover"]

    with_capital = seeded.get("/api/items", params={"min_score": 60, "capital": 50_000_000})

    assert set(names(with_capital)) == {"Slow mover", "Fast mover"}
    assert with_capital.json()["total"] == 2


def test_sorting_by_score_with_capital_orders_by_the_recomputed_score(seeded):
    big = seeded.get("/api/items", params={"sort": "score", "order": "desc", "capital": 5_000_000_000_000})
    small_asc = seeded.get("/api/items", params={"sort": "score", "order": "asc", "capital": 50_000_000})

    scores = [i["score"] for i in big.json()["items"]]
    assert scores == sorted(scores, reverse=True)
    asc_scores = [i["score"] for i in small_asc.json()["items"]]
    assert asc_scores == sorted(asc_scores)


def test_eligibility_filter_and_pagination_work_on_the_recomputed_results(seeded):
    page = seeded.get("/api/items", params={"capital": 50_000_000, "eligibility": "RECOMMENDED", "limit": 1})

    body = page.json()
    assert all(i["eligibility"] == "RECOMMENDED" for i in body["items"])
    assert body["limit"] == 1 and len(body["items"]) <= 1


def test_items_without_a_score_are_left_untouched_by_the_capital(client):
    api_client, db_path = client
    seed_item(db_path, type_id=40, name="Unscored")

    item = api_client.get("/api/items", params={"capital": 50_000_000}).json()["items"][0]

    assert item["score"] is None and item["eligibility"] is None


@pytest.mark.parametrize("capital", [1, 999_999, 2e13, -5])
def test_a_capital_out_of_range_is_rejected(seeded, capital):
    assert seeded.get("/api/items", params={"capital": capital}).status_code == 422
    assert seeded.get("/api/items/34", params={"capital": capital}).status_code == 422


def test_the_detail_with_a_capital_recomputes_the_header_and_the_panel_for_that_capital(seeded):
    default = seeded.get("/api/items/34").json()
    custom = seeded.get("/api/items/34", params={"capital": 50_000_000}).json()

    assert custom["assessment"]["capital"] == 50_000_000
    assert custom["assessment"]["score"]["reference"]["capital"] == 50_000_000
    assert custom["assessment"]["config_changed"] is False
    assert custom["status"]["score"] == round(custom["assessment"]["score"]["total"])
    assert custom["status"]["score"] > default["status"]["score"]
    assert default["assessment"]["capital"] is None
    assert default["assessment"]["score"]["reference"]["capital"] == 1_000_000_000


def test_the_capital_only_changes_the_capital_dependent_factors(seeded):
    base = seeded.get("/api/items/34").json()["assessment"]["score"]["factors"]
    small = seeded.get("/api/items/34", params={"capital": 50_000_000}).json()["assessment"]["score"]["factors"]

    scores = lambda factors: {f["key"]: f["score"] for f in factors}  # noqa: E731
    assert scores(base)["profitability"] == scores(small)["profitability"]
    assert scores(base)["volume"] == scores(small)["volume"]
    assert scores(base)["stability"] == scores(small)["stability"]
    assert scores(small)["liquidity"] > scores(base)["liquidity"]


def test_the_recomputed_market_is_cached_per_capital_and_expires_with_the_next_cycle(seeded, client):
    from backend.api import main as api_main

    _, db_path = client
    api_main._RESCORE_CACHE.clear()

    seeded.get("/api/items", params={"capital": 50_000_000, "min_score": 1})
    assert len(api_main._RESCORE_CACHE) == 1
    seeded.get("/api/items", params={"capital": 50_000_000, "sort": "score"})   # otro filtro, mismo capital
    assert len(api_main._RESCORE_CACHE) == 1
    seeded.get("/api/items", params={"capital": 80_000_000, "min_score": 1})    # otro capital
    assert len(api_main._RESCORE_CACHE) == 2

    conn = sqlite3.connect(db_path)                                             # llega un ciclo nuevo
    conn.execute("UPDATE item_status SET last_evaluated_at = '2099-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    seeded.get("/api/items", params={"capital": 50_000_000, "min_score": 1})
    assert len(api_main._RESCORE_CACHE) == 3                                    # entrada nueva, la vieja caduca por LRU


def test_the_cache_never_grows_past_its_limit(seeded):
    from backend.api import main as api_main

    api_main._RESCORE_CACHE.clear()
    for capital in range(1, 12):
        seeded.get("/api/items", params={"capital": capital * 10_000_000, "min_score": 1})

    assert len(api_main._RESCORE_CACHE) == api_main._RESCORE_CACHE_MAX


def test_a_changed_setting_is_not_served_from_a_stale_cache_entry(seeded, client):
    from backend.api import main as api_main

    _, db_path = client
    api_main._RESCORE_CACHE.clear()
    before = by_name(seeded.get("/api/items", params={"capital": 50_000_000, "min_score": 0}))["Slow mover"]["score"]

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_settings SET value = 0.5 WHERE key = 'score_w_profitability'")  # pesos distintos
    conn.commit()
    conn.close()
    after = by_name(seeded.get("/api/items", params={"capital": 50_000_000, "min_score": 0}))["Slow mover"]["score"]

    assert after != before and len(api_main._RESCORE_CACHE) == 2


@pytest.mark.parametrize("asked,used", [(50_000_000, 50_000_000), (123_000_000, 120_000_000),
                                         (1_000_000, 1_000_000), (1_551_000_000, 1_600_000_000),
                                         (999_999_999, 1_000_000_000)])
def test_the_capital_is_snapped_to_two_significant_digits_and_the_snapped_value_is_echoed(seeded, asked, used):
    body = seeded.get("/api/items", params={"capital": asked}).json()

    assert body["capital"] == used
    assert seeded.get("/api/items/34", params={"capital": asked}).json()["assessment"]["capital"] == used


def test_nearby_capitals_share_one_cache_entry(seeded):
    from backend.api import main as api_main

    api_main._RESCORE_CACHE.clear()
    seeded.get("/api/items", params={"capital": 120_000_000, "min_score": 1})
    seeded.get("/api/items", params={"capital": 123_400_000, "min_score": 1})

    assert len(api_main._RESCORE_CACHE) == 1


def test_filtered_and_sorted_results_match_a_brute_force_reference(client):
    """El camino rápido (ids primero, página después) da exactamente lo que daría filtrar todo a mano."""
    import random

    api_client, db_path = client
    rng = random.Random(4)
    classes = ("EXCELLENT", "HIGH", "MODERATE", "LOW", "DISCARDED")
    for i in range(60):
        make_scored(db_path, 100 + i, f"Item {i}", volume=10 ** rng.uniform(3, 9), stored_score=rng.randint(0, 100),
                    depth=(int(10 ** rng.uniform(1, 9)), int(10 ** rng.uniform(1, 9))))
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE item_status SET roi = ?, buy_order_count = ?, avg_daily_order_count_7d = ?, "
                     "status = ? WHERE type_id = ?",
                     (rng.uniform(0.03, 1.4), rng.choice([0, 2, 12, 40]),   # ROI único: el desempate por ROI es determinista
                      rng.choice([1, 8, 40, 200]), rng.choice(["POTENCIAL", "EN_OBSERVACION", "DESCARTADO"]),
                      100 + i))
        conn.commit()
        conn.close()
    conn = sqlite3.connect(db_path)                       # y unos sin puntaje, que deben quedar siempre al final
    conn.execute("UPDATE item_status SET score_version = NULL, score = NULL, score_class = NULL, "
                 "eligibility = NULL, recommendation = NULL WHERE type_id IN (100, 101, 102)")
    conn.commit()
    conn.close()

    for capital in (50_000_000, 1_000_000_000, 5_000_000_000, 123_000_000):
        everything = api_client.get("/api/items", params={"capital": capital, "limit": 500}).json()["items"]
        assert len(everything) == 60

        def reference(sort=None, order="desc", **filters):
            rows = list(everything)
            if "min_score" in filters:
                rows = [r for r in rows if r["score"] is not None and r["score"] >= filters["min_score"]]
            for key in ("score_class", "eligibility", "recommendation"):
                if key in filters:
                    rows = [r for r in rows if r[key] == filters[key]]
            if sort == "score":
                sign = -1 if order == "desc" else 1
                rows.sort(key=lambda r: -r["roi"])
                rows.sort(key=lambda r: (r["score"] is None, sign * (r["score"] or 0)))
            return [r["type_id"] for r in rows]

        cases = [dict(sort="score", order="desc"), dict(sort="score", order="asc"),
                 dict(min_score=50), dict(min_score=50, sort="score", order="desc"),
                 dict(score_class="LOW"), dict(eligibility="RECOMMENDED", sort="score", order="asc"),
                 dict(recommendation="WAIT"), dict(score_class=rng.choice(classes), min_score=10, sort="score"),
                 dict(eligibility="NO_ELIGIBLE", recommendation="REJECT", sort="score", order="desc")]
        for case in cases:
            params = {"capital": capital, "limit": 500, **{k: v for k, v in case.items()}}
            body = api_client.get("/api/items", params=params).json()
            expected = reference(**case)

            assert [i["type_id"] for i in body["items"]] == expected, (capital, case)
            assert body["total"] == len(expected), (capital, case)
            page = api_client.get("/api/items", params={**params, "limit": 7, "offset": 5}).json()
            assert [i["type_id"] for i in page["items"]] == expected[5:12], (capital, case, "paginación")
            # lo mostrado en cada fila es el puntaje recalculado, el mismo que en la lista completa
            scores = {r["type_id"]: (r["score"], r["eligibility"], r["recommendation"]) for r in everything}
            assert all((i["score"], i["eligibility"], i["recommendation"]) == scores[i["type_id"]] for i in body["items"])
