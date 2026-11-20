# ruff: noqa: F811
"""Screener personalizado (fase 5 de EF-02): ROI, estado y puntaje con las comisiones del jugador (?profile=mine)."""
import json
import random
import sqlite3

import pytest
from fastapi.testclient import TestClient

from analytics.classification import classify
from analytics.eve_calculator import EveCalculatorConfig, config_from_settings, evaluar_spread, roi
from analytics.opportunity import evaluate_item
from analytics.scoring import ScoreInputs
from backend.api.main import app
from backend.api.personalize import personal_settings, personalize_row, roi_filter_sql
from finance.fees import Profile
from finance.user_profile import screener_factors
from storage.db import get_app_settings_dict, init_db
from tests.conftest import seed_item
from tests.test_profile import api  # noqa: F401  (fixture: sesión iniciada con ESI simulado)

# Perfil de la sesión simulada (tests/test_profile.py): Broker Relations V, Accounting IV, standing de facción 3 con
# Jita → broker 1,41 %, sales tax 4,2 % → factores 0,9439 / 1,0141 (los de referencia son 0,901 / 1,024).
ST, BF = 0.9439, 1.0141


def put_item(db_path, type_id, name, buy, sell, *, vol7=1000.0, ops=100.0, liquidez="Buena", sane=True):
    """Un ítem tal como lo deja el motor con las comisiones de referencia (mismas funciones, mismos ajustes)."""
    seed_item(db_path, type_id=type_id, name=name)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    settings = get_app_settings_dict(conn)
    cfg = config_from_settings(EveCalculatorConfig, settings)
    spread = sell / buy - 1
    spread_eval = evaluar_spread(spread, cfg)
    if sane:
        status, reason = classify(spread_eval, liquidez, vol7, ops, min_daily_volume_7d=settings["min_daily_volume_7d"],
                                  min_daily_order_count_7d=settings["min_daily_order_count_7d"])
    else:
        status, reason = "DESCARTADO", "precio incoherente con el histórico"
    stored_roi = round(roi(spread, cfg), 4)
    extras = {"cv": 0.03, "age": 1.0, "sane": sane, "bd": 10**9, "sd": 10**9}
    score, assessment = evaluate_item(
        ScoreInputs(roi=stored_roi, best_buy=buy, volume_7d=vol7, volume_30d=vol7 * 5, ops_7d=ops, buy_orders=40,
                    sell_orders=40, status=status, price_cv=0.03, buy_depth=10**9, sell_depth=10**9), sell, extras, settings)
    conn.execute("UPDATE market_snapshot SET best_buy = ?, best_sell = ? WHERE type_id = ?", (buy, sell, type_id))
    conn.execute(
        "UPDATE item_status SET status = ?, reason = ?, spread_bruto = ?, evaluacion_spread = ?, liquidez = ?, roi = ?, "
        "best_buy = ?, best_sell = ?, avg_daily_volume_7d = ?, avg_daily_order_count_7d = ?, volumen_diario_real = ?, "
        "buy_order_count = 40, sell_order_count = 40, score = ?, score_class = ?, eligibility = ?, recommendation = ?, "
        "score_version = ?, score_inputs = ? WHERE type_id = ?",
        (status, reason, round(spread, 4), spread_eval, liquidez, stored_roi, buy, sell, vol7, ops, vol7 * 5, score.score,
         score.classification, assessment["eligibility"]["status"], assessment["recommendation"]["action"], score.version,
         json.dumps(extras), type_id))
    conn.commit()
    conn.close()


@pytest.fixture
def world(client, api):  # noqa: F811
    """Mercado con tres ítems y un jugador con sesión y su perfil leído de ESI."""
    _, db_path = client
    put_item(db_path, 101, "Borderline", 1000, 1150)                 # spread 15 %: «Pequeño beneficio» con las comisiones de referencia
    put_item(db_path, 102, "Lossmaker", 1000, 1100)                  # spread 10 %: «Pérdida» de referencia, pero rentable con las del jugador
    put_item(db_path, 103, "Garbage", 1000, 5000, sane=False)        # precio incoherente: siempre descartado
    api.get("/api/me/profile")                                       # lee el perfil de ESI
    return api, TestClient(app), db_path


def items(response):
    return {i["name"]: i for i in response.json()["items"]}


# ---- Las bandas de spread se trasladan sin cambiar el ROI neto que marcan ------------------------------------------

def test_default_profile_reproduces_the_historic_screener_factors():
    assert screener_factors(Profile(source="MANUAL")) == (0.901, 1.024)
    assert screener_factors(Profile(5, 0, 5, source="MANUAL")) == (0.9513, 1.015)   # 1 − 3,375 % − 1,5 % ; 1 + 1,5 %


def test_bands_are_unchanged_when_the_player_pays_the_reference_fees():
    base = {"sales_tax_factor": 0.901, "buy_fee_factor": 1.024, "spread_perdida_max": 0.14, "spread_casi_cero_max": 0.15,
            "spread_pequeno_max": 0.20, "spread_buen_margen_max": 0.30, "spread_muy_bueno_max": 0.50}
    assert personal_settings(base, 0.901, 1.024) == base


def test_a_band_marks_the_same_net_roi_with_any_fees():
    """«Pérdida» = ROI neto por debajo del mismo tramo, pagues las comisiones que pagues."""
    base = {"sales_tax_factor": 0.901, "buy_fee_factor": 1.024, "spread_perdida_max": 0.14, "spread_casi_cero_max": 0.15,
            "spread_pequeno_max": 0.20, "spread_buen_margen_max": 0.30, "spread_muy_bueno_max": 0.50}
    base_cfg = config_from_settings(EveCalculatorConfig, base)
    rng = random.Random(7)
    for _ in range(400):
        st, bf = round(rng.uniform(0.85, 0.99), 4), round(rng.uniform(1.0, 1.04), 4)
        own_cfg = config_from_settings(EveCalculatorConfig, personal_settings(base, st, bf))
        spread = rng.uniform(0.0, 0.8)
        same_roi_base_spread = (1 + spread) * (st / bf) / (0.901 / 1.024) - 1       # spread de referencia con el mismo ROI neto
        assert evaluar_spread(spread, own_cfg) == evaluar_spread(same_roi_base_spread, base_cfg)


def test_personalizing_with_the_reference_fees_changes_nothing_for_any_item(tmp_path):
    path = str(tmp_path / "m.db")
    init_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    settings = get_app_settings_dict(conn)
    cfg = config_from_settings(EveCalculatorConfig, settings)
    rng = random.Random(3)
    for _ in range(300):
        buy = round(rng.uniform(5, 5_000_000), 2)
        sell = round(buy * rng.uniform(0.95, 1.9), 2)
        vol7, ops = rng.uniform(0, 5000), rng.uniform(0, 300)
        liquidez = rng.choice(["Excelente liquidez", "Buena", "Aceptable", "Cuidado", "Muy lenta para tu capital"])
        spread = sell / buy - 1
        spread_eval = evaluar_spread(spread, cfg)
        status, reason = classify(spread_eval, liquidez, vol7, ops, min_daily_volume_7d=settings["min_daily_volume_7d"],
                                  min_daily_order_count_7d=settings["min_daily_order_count_7d"])
        row = {"best_buy": buy, "best_sell": sell, "roi": round(roi(spread, cfg), 4), "evaluacion_spread": spread_eval,
               "status": status, "reason": reason, "liquidez": liquidez, "avg_daily_volume_7d": vol7,
               "avg_daily_order_count_7d": ops, "score_inputs": json.dumps({"sane": True})}
        assert personalize_row(row, settings) == row
    conn.close()


def test_roi_filter_sql_is_exact():
    fv, fc = 0.9439, 1.0141
    sql = roi_filter_sql("b", "s", {"sales_tax_factor": fv, "buy_fee_factor": fc}, ">=")
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (b REAL, s REAL)")
    rows = [(1000.0, 1150.0), (1000.0, 1100.0), (0.0, 5.0), (-1.0, 5.0), (2000.0, 2300.0)]
    db.executemany("INSERT INTO t VALUES (?, ?)", rows)
    for minimum in (-0.5, 0.0, 0.05, 0.0704, 0.0705, 0.2):
        got = {r for r in db.execute(f"SELECT b, s FROM t WHERE {sql}", (minimum,))}
        want = {(b, s) for b, s in rows if b > 0 and s * fv / (b * fc) - 1 >= minimum - 1e-12}
        assert got == want, minimum


# ---- API -----------------------------------------------------------------------------------------------------------

def test_anonymous_requests_are_untouched(world):
    _, anon, _ = world
    body = anon.get("/api/items").json()
    assert body["profile"] is None
    rows = items(anon.get("/api/items"))
    assert rows["Borderline"]["roi"] == pytest.approx(0.0119, abs=1e-4) and rows["Borderline"]["status"] == "EN_OBSERVACION"
    assert rows["Lossmaker"]["status"] == "DESCARTADO"


def test_profile_mine_needs_a_session_and_a_valid_value(world, tmp_path, monkeypatch):
    _, anon, _ = world
    assert anon.get("/api/items?profile=mine").status_code == 401
    assert anon.get("/api/items/101?profile=mine").status_code == 401
    assert anon.get("/api/items?profile=theirs").status_code == 422
    for name in ("EVE_LOGIN_CLIENT_ID", "EVE_LOGIN_CLIENT_SECRET", "USERS_ENC_KEYS"):
        monkeypatch.delenv(name, raising=False)
    assert anon.get("/api/items?profile=mine").status_code == 503


def test_the_list_shows_the_players_roi_bands_and_status(world):
    api, _, _ = world
    r = api.get("/api/items?profile=mine")
    assert r.status_code == 200
    rows = items(r)
    assert rows["Borderline"]["roi"] == 0.0704 and rows["Borderline"]["evaluacion_spread"] == "🟢 Buen margen"
    assert rows["Borderline"]["status"] == "POTENCIAL"                     # con sus comisiones ya cumple «Buen margen»
    assert rows["Lossmaker"]["roi"] == 0.0239 and rows["Lossmaker"]["status"] == "EN_OBSERVACION"   # antes «Pérdida»
    assert rows["Garbage"]["status"] == "DESCARTADO" and "incoherente" in rows["Garbage"]["reason"]
    assert rows["Borderline"]["spread_bruto"] == 0.15                      # el spread bruto no depende de las comisiones
    assert r.json()["profile"]["personalized"] is True and r.json()["profile"]["broker_fee_pct"] == 1.41
    assert r.json()["profile"]["sales_tax_pct"] == 4.2 and r.json()["profile"]["market_id"] == "jita"


def test_personal_responses_are_never_cacheable(world):
    api, _, _ = world
    for url in ("/api/items?profile=mine", "/api/items/101?profile=mine"):
        headers = api.get(url).headers
        assert headers["cache-control"] == "private, no-store" and "Cookie" in headers["vary"]


def test_status_filter_uses_the_players_status(world):
    api, anon, _ = world
    assert set(items(api.get("/api/items?profile=mine&status=POTENCIAL"))) == {"Borderline"}
    assert set(items(api.get("/api/items?profile=mine&status=EN_OBSERVACION"))) == {"Lossmaker"}
    assert set(items(api.get("/api/items?profile=mine&status=DESCARTADO"))) == {"Garbage"}
    assert set(items(anon.get("/api/items?status=DESCARTADO"))) == {"Lossmaker", "Garbage"}      # sin perfil, lo de siempre
    body = api.get("/api/items?profile=mine&status=POTENCIAL").json()
    assert body["total"] == 1


def test_roi_filters_use_the_players_roi(world):
    api, anon, _ = world
    assert set(items(api.get("/api/items?profile=mine&min_roi=0.05"))) >= {"Borderline"}
    assert "Lossmaker" not in items(api.get("/api/items?profile=mine&min_roi=0.05"))
    assert set(items(api.get("/api/items?profile=mine&max_roi=0.03"))) >= {"Lossmaker"}
    assert "Borderline" not in items(api.get("/api/items?profile=mine&max_roi=0.03"))
    assert "Borderline" not in items(anon.get("/api/items?min_roi=0.05"))                       # con el ROI de referencia no llega
    both = api.get("/api/items?profile=mine&min_roi=0.02&max_roi=0.05").json()
    assert {i["name"] for i in both["items"]} == {"Lossmaker"} and both["total"] == 1


def test_the_page_path_and_the_full_market_path_agree(world):
    api, _, _ = world
    page = items(api.get("/api/items?profile=mine"))
    full = items(api.get("/api/items?profile=mine&min_score=0"))               # recorre todo el mercado
    for name, row in full.items():
        for key in ("roi", "status", "evaluacion_spread", "score", "score_class", "eligibility", "recommendation", "reason"):
            assert row[key] == page[name][key], (name, key)


def test_sorting_and_filtering_by_score_work_with_the_players_fees(world):
    api, _, _ = world
    body = api.get("/api/items?profile=mine&sort=score&order=desc").json()
    scores = [i["score"] for i in body["items"] if i["score"] is not None]
    assert scores == sorted(scores, reverse=True) and body["profile"]["personalized"] is True
    everything = items(api.get("/api/items?profile=mine"))
    kept = api.get("/api/items?profile=mine&min_score=60").json()
    assert {i["name"] for i in kept["items"]} == {n for n, i in everything.items() if (i["score"] or 0) >= 60}
    assert kept["total"] == len(kept["items"])


def test_the_players_fees_change_the_score_inputs_not_only_the_label(world):
    api, anon, _ = world
    own, ref = items(api.get("/api/items?profile=mine"))["Lossmaker"], items(anon.get("/api/items"))["Lossmaker"]
    assert own["score"] != ref["score"] or own["eligibility"] != ref["eligibility"]
    assert ref["eligibility"] == "NO_ELIGIBLE"


def test_item_detail_uses_the_players_fees_everywhere(world):
    api, anon, _ = world
    own = api.get("/api/items/102?profile=mine").json()
    ref = anon.get("/api/items/102").json()
    assert own["status"]["roi"] == 0.0239 and own["status"]["status"] == "EN_OBSERVACION"
    assert ref["status"]["status"] == "DESCARTADO" and ref["profile"] is None
    assert own["profile"]["broker_fee_pct"] == 1.41
    assert "NET_PROFIT_POSITIVE" in own["assessment"]["eligibility"]["passed_filters"]
    assert "CLASSIFIED_DISCARDED" in ref["assessment"]["eligibility"]["failed_filters"]
    rec_own, rec_ref = own["recommendation"], ref["recommendation"]
    unit_own = rec_own["beneficio_neto_isk"] / rec_own["unidades_sugeridas"]
    unit_ref = rec_ref["beneficio_neto_isk"] / rec_ref["unidades_sugeridas"] if rec_ref["unidades_sugeridas"] else None
    assert unit_own == pytest.approx(1100 * ST - 1000 * BF, rel=0.01)           # beneficio por unidad con SUS comisiones
    assert unit_ref is None or unit_ref < unit_own
    assert rec_own["precio_unidad_isk"] == round(1000 * BF)


def test_a_player_with_the_reference_fees_sees_exactly_the_reference_numbers(client, api):  # noqa: F811
    _, db_path = client
    put_item(db_path, 101, "Borderline", 1000, 1150)
    # Sin leer su perfil de ESI el jugador tiene el perfil por defecto: 0,901 / 1,024.
    body = api.get("/api/items?profile=mine").json()
    assert body["profile"]["personalized"] is False and body["profile"]["source"] == "MANUAL"
    assert body["items"] == api.get("/api/items").json()["items"]
    assert api.get("/api/items/101?profile=mine").json()["status"] == api.get("/api/items/101").json()["status"]


def test_unscored_items_also_get_the_players_roi(world):
    api, _, db_path = world
    seed_item(db_path, type_id=200, name="Unscored")                           # compra 4,0, venta 4,5 y sin puntaje
    row = items(api.get("/api/items?profile=mine"))["Unscored"]
    assert row["roi"] == round(4.5 * ST / (4.0 * BF) - 1, 4) and row["score"] is None


def test_other_visitors_never_see_personal_numbers_after_a_personal_request(world):
    api, anon, _ = world
    api.get("/api/items?profile=mine&min_score=0")
    again = items(anon.get("/api/items?min_score=0"))
    assert again["Borderline"]["status"] == "EN_OBSERVACION" and again["Borderline"]["roi"] == pytest.approx(0.0119, abs=1e-4)
    assert anon.get("/api/items?profile=mine").status_code == 401


def test_capital_and_profile_combine(world):
    api, _, _ = world
    body = api.get("/api/items?profile=mine&capital=50000000&min_score=0").json()
    assert body["capital"] == 50_000_000 and body["profile"]["personalized"] is True
    assert {i["name"]: i["status"] for i in body["items"]}["Borderline"] == "POTENCIAL"


def test_each_market_uses_its_own_station_owner(world):
    api, _, _ = world
    conn = sqlite3.connect(world[2])
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = 'amarr'")
    conn.commit()
    conn.close()
    # Los standings simulados solo valen para Jita (facción Caldari): en Amarr el jugador no tiene standing y paga más broker.
    jita = api.get("/api/items?profile=mine&market=jita").json()["profile"]
    amarr = api.get("/api/items?profile=mine&market=amarr").json()["profile"]
    assert jita["broker_fee_pct"] == 1.41 and amarr["broker_fee_pct"] == 1.5 and amarr["market_id"] == "amarr"
