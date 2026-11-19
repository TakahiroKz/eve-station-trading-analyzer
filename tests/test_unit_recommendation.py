"""La recomendación de unidades del detalle sale del capital elegido (10 % por posición)."""
import sqlite3

import pytest

from tests.test_capital_api import make_scored

BUY, SELL = 1000.0, 1300.0
UNIT_PROFIT = SELL * 0.901 - BUY * 1.024   # comisiones por defecto del motor


def prices(db_path, type_id, buy=BUY, sell=SELL):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market_snapshot SET best_buy = ?, best_sell = ? WHERE type_id = ?", (buy, sell, type_id))
    conn.execute("UPDATE item_status SET best_buy = ?, best_sell = ? WHERE type_id = ?", (buy, sell, type_id))
    conn.commit()
    conn.close()


@pytest.fixture
def seeded(client):
    api_client, db_path = client
    make_scored(db_path, 34, "Fast mover", volume=50_000_000, stored_score=90)
    make_scored(db_path, 35, "Slow mover", volume=200_000, stored_score=40)
    for type_id in (34, 35):
        prices(db_path, type_id)
    return api_client, db_path


def reco(api_client, type_id=34, **params):
    return api_client.get(f"/api/items/{type_id}", params=params).json()["recommendation"]


def test_without_a_capital_the_reference_capital_and_a_ten_percent_position_are_used(seeded):
    block = reco(seeded[0])

    assert block["capital"] == 1_000_000_000 and block["position_pct"] == 0.1
    assert block["posicion_isk"] == 100_000_000
    assert block["volumen_deseado"] == pytest.approx(100_000)          # 100 M ISK / 1000 ISK
    assert block["unidades_sugeridas"] == 100_000 and block["action"] == "BUY_CANDIDATE"


def test_the_suggested_units_follow_the_chosen_capital(seeded):
    small = reco(seeded[0], capital=50_000_000)
    big = reco(seeded[0], capital=5_000_000_000)

    assert small["capital"] == 50_000_000 and small["posicion_isk"] == 5_000_000
    assert small["unidades_sugeridas"] == 5_000 and big["unidades_sugeridas"] == 500_000
    assert big["unidades_sugeridas"] == small["unidades_sugeridas"] * 100


def test_the_capital_is_snapped_like_everywhere_else_and_the_snapped_value_is_what_is_used(seeded):
    block = reco(seeded[0], capital=123_000_000)

    assert block["capital"] == 120_000_000 and block["posicion_isk"] == 12_000_000
    assert block["unidades_sugeridas"] == 12_000


def test_liquidity_trims_the_units_when_the_position_is_too_big_for_the_market(seeded):
    # Volumen diario 200.000: con 5.000 M de capital la posición (500.000 u) supera 2 veces el volumen del día.
    block = reco(seeded[0], type_id=35, capital=5_000_000_000)

    assert block["volumen_deseado"] == pytest.approx(500_000)
    assert 0 < block["unidades_sugeridas"] <= 0.4 * 200_000
    assert "Baja el volumen" in block["recomendacion"]


def test_the_amounts_are_consistent_with_the_units(seeded):
    block = reco(seeded[0], capital=250_000_000)

    units = block["unidades_sugeridas"]
    assert units == 25_000
    assert block["inversion_isk"] == round(units * BUY * 1.024)
    assert block["beneficio_neto_isk"] == pytest.approx(units * UNIT_PROFIT, abs=units * 0.01)
    assert block["dias_rotacion"] == pytest.approx(units / (50_000_000 * 0.1), abs=0.006)  # redondeado a 2 decimales


def test_a_rejected_item_gets_zero_units_and_says_why(seeded):
    api_client, db_path = seeded
    prices(db_path, 35, buy=1000.0, sell=900.0)        # vender por debajo del costo: beneficio negativo

    block = reco(api_client, type_id=35)

    assert block["action"] == "REJECT" and block["unidades_sugeridas"] == 0
    assert "NET_PROFIT_NOT_POSITIVE" in block["blocked_by"]
    assert block["inversion_isk"] == 0 and block["beneficio_neto_isk"] == 0 and block["dias_rotacion"] is None


def test_an_item_without_a_score_still_gets_units_but_no_action(client):
    api_client, db_path = client
    from tests.conftest import seed_item

    seed_item(db_path, type_id=50, name="Unscored")
    prices(db_path, 50)

    block = reco(api_client, type_id=50, capital=100_000_000)

    assert block["action"] is None and block["blocked_by"] == []
    assert block["unidades_sugeridas"] >= 0 and block["capital"] == 100_000_000


def test_an_item_without_prices_has_no_recommendation(client):
    api_client, db_path = client
    from tests.conftest import seed_item

    seed_item(db_path, type_id=51, name="No prices")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market_snapshot SET best_buy = NULL, best_sell = NULL WHERE type_id = 51")
    conn.execute("UPDATE item_status SET best_buy = 0, best_sell = 0 WHERE type_id = 51")
    conn.commit()
    conn.close()

    assert api_client.get("/api/items/51").json()["recommendation"] is None


def test_the_old_per_cycle_log_is_still_returned_but_is_no_longer_the_recommendation(seeded):
    body = seeded[0].get("/api/items/34").json()

    assert "latest_opportunities" in body and body["recommendation"] is not None
