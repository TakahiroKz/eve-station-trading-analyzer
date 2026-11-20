"""Simulador financiero (fase 4 de EF-02): libro de la estación, /api/finance/evaluate|compare y escenarios guardados."""
import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import finance as finance_module
from backend.api.main import app
from ingestion import station_book
from ingestion.station_book import BookUnavailable, fetch_station_book
from storage import users_db
from tests.test_profile import api  # noqa: F401  (fixture: sesión iniciada con ESI simulado)

STATION = 60003760
BASE = {"market_id": "jita", "units": 100, "buy_price": "1000", "sell_price": "1200"}


# ---- Libro de la estación -------------------------------------------------------------------------------------------

def order(price, volume, buy, location=STATION):
    return {"price": price, "volume_remain": volume, "is_buy_order": buy, "location_id": location}


@pytest.fixture(autouse=True)
def _clean_cache():
    station_book.clear_cache()
    yield
    station_book.clear_cache()


def fake_pages(monkeypatch, pages, calls=None, status=200):
    def _get(url, params=None, headers=None, timeout=None):
        if calls is not None:
            calls.append(params["page"])
        if status != 200:
            return httpx.Response(status, request=httpx.Request("GET", url))
        return httpx.Response(200, json=pages[params["page"] - 1], headers={"X-Pages": str(len(pages))},
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", _get)


def test_book_keeps_only_the_station_groups_by_price_and_sorts(monkeypatch):
    fake_pages(monkeypatch, [[order(10.5, 5, False), order(10.5, 7, False), order(9.0, 3, False), order(8, 100, False, 99),
                              order(7.0, 4, True), order(7.5, 6, True), order(99, 9, True, 99)]])
    book = fetch_station_book(10000002, STATION, 34)
    assert book["asks"] == [["9.0", "3"], ["10.5", "12"]] and book["bids"] == [["7.5", "6"], ["7.0", "4"]]
    assert book["cached"] is False


def test_book_ignores_garbage_orders(monkeypatch):
    fake_pages(monkeypatch, [[order(0, 5, False), order(-1, 5, False), order(5, 0, False), {"price": "x", "location_id": STATION},
                              {"location_id": STATION}, order(float("inf"), 3, False), order(6, 2, False)]])
    assert fetch_station_book(1, STATION, 1)["asks"] == [["6", "2"]]


def test_book_reads_every_page_and_caps_levels(monkeypatch):
    calls = []
    page1 = [order(float(i + 1), 1, False) for i in range(150)]
    page2 = [order(float(i + 1000), 1, False) for i in range(150)]
    fake_pages(monkeypatch, [page1, page2], calls)
    book = fetch_station_book(1, STATION, 1)
    assert calls == [1, 2] and len(book["asks"]) == 200 and book["asks"][0] == ["1.0", "1"]


def test_book_is_cached_for_a_minute(monkeypatch):
    calls = []
    fake_pages(monkeypatch, [[order(5, 1, False)]], calls)
    first = fetch_station_book(1, STATION, 1, now=1000.0)
    again = fetch_station_book(1, STATION, 1, now=1059.0)
    assert calls == [1] and again["cached"] is True and again["asks"] == first["asks"]
    fetch_station_book(1, STATION, 1, now=1060.0)
    assert calls == [1, 1]
    fetch_station_book(1, STATION, 2, now=1060.0)                 # otro ítem: otra consulta
    assert calls == [1, 1, 1]


def test_book_404_means_no_orders_and_other_errors_are_unavailable(monkeypatch):
    fake_pages(monkeypatch, [[]], status=404)
    assert fetch_station_book(1, STATION, 1)["asks"] == []
    station_book.clear_cache()
    for code in (500, 420, 403):
        fake_pages(monkeypatch, [[]], status=code)
        with pytest.raises(BookUnavailable):
            fetch_station_book(1, STATION, 1)


def test_book_network_failure_and_garbage_body(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(BookUnavailable):
        fetch_station_book(1, STATION, 1)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, content=b"<html>", request=httpx.Request("GET", "http://x")))
    with pytest.raises(BookUnavailable):
        fetch_station_book(1, STATION, 1)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"a": 1}, request=httpx.Request("GET", "http://x")))
    with pytest.raises(BookUnavailable):
        fetch_station_book(1, STATION, 1)


# ---- /api/finance/evaluate ------------------------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app, follow_redirects=False)


def ev(client, **extra):
    return client.post("/api/finance/evaluate", json={**BASE, **extra})


def test_default_profile_reproduces_the_historic_factors(client):
    r = ev(client)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    a = r.json()["assessment"]
    assert a["calculation_status"] == "VALID" and a["warnings"] == []
    assert Decimal(a["rates"]["broker_fee"]) == Decimal("0.024") and Decimal(a["rates"]["sales_tax"]) == Decimal("0.075")
    # por unidad: 1200·0,901 − 1000·1,024 = 57,2 → ×100
    assert a["result"]["net_profit"] == "5720.00" and a["result"]["capital_outlay"] == "102400.00"
    assert r.json()["profile"]["mode"] == "default" and r.json()["book"] is None
    assert a["engine_version"] and a["rules_version"]


def test_manual_profile_changes_the_numbers(client):
    r = ev(client, profile_mode="manual", manual_profile={"broker_relations": 5, "accounting": 5})
    a = r.json()["assessment"]
    assert Decimal(a["rates"]["broker_fee"]) == Decimal("0.015") and Decimal(a["rates"]["sales_tax"]) == Decimal("0.03375")
    assert a["result"]["net_profit"] == "12650.00"
    assert r.json()["profile"]["broker_relations"] == 5


def test_targets_and_capital_check(client):
    a = ev(client, target_roi_percent=10, available_capital="50000").json()["assessment"]
    assert Decimal(a["targets"]["target_sell_price"]) > Decimal(a["targets"]["break_even_sell_price"]) > Decimal(1000)
    # ROI objetivo 10 % sobre 102.400 de capital: 100·s·0,901 = 102.400·1,10 → s = 1250,17 (y no 10 veces más)
    assert Decimal(a["targets"]["target_sell_price"]) == Decimal("1250.17")
    assert a["capital"]["affordable"] is False and a["capital"]["max_units"] == 48
    assert ev(client, available_capital="500000").json()["assessment"]["capital"]["affordable"] is True


def test_immediate_modes_walk_the_explicit_book(client):
    r = ev(client, buy_mode="IMMEDIATE", buy_price=None, asks=[["1000", 40], ["1100", 100]],
           sell_mode="IMMEDIATE", sell_price=None, bids=[["1300", 30], ["1250", 500]])
    a = r.json()["assessment"]
    assert a["calculation_status"] == "VALID"
    assert a["result"]["buy_price"] == "1060.00"                      # (40·1000 + 60·1100) / 100
    assert a["result"]["sell_price"] == "1265.00"                     # (30·1300 + 70·1250) / 100 → compra inmediata sin broker
    assert "UNVERIFIED_RULE:R9" in a["warnings"]


def test_not_enough_liquidity_is_reported_not_crashed(client):
    a = ev(client, buy_mode="IMMEDIATE", buy_price=None, asks=[["1000", 10]]).json()["assessment"]
    assert "PARTIAL_FILL:asks:10/100" in a["warnings"] and a["result"]["units"] == "10"
    empty = ev(client, buy_mode="IMMEDIATE", buy_price=None).json()["assessment"]
    assert empty["calculation_status"] == "INCOMPLETE" and "NO_LIQUIDITY:asks" in empty["warnings"]


def test_upwell_needs_the_owner_fee_and_flags_the_unverified_rule(client):
    a = ev(client, venue="UPWELL").json()["assessment"]
    assert a["calculation_status"] == "INCOMPLETE" and "MISSING:owner_fee_pct" in a["warnings"]
    ok = ev(client, venue="UPWELL", owner_fee_percent=1.5).json()["assessment"]
    assert ok["calculation_status"] == "VALID" and Decimal(ok["rates"]["broker_fee"]) == Decimal("0.02")
    assert "UNVERIFIED_RULE:R6" in ok["warnings"]


def test_relists_add_cost_and_flag_the_discrepant_rule(client):
    base = ev(client).json()["assessment"]["result"]
    a = ev(client, relists=[{"side": "SELL", "old_price": "1200", "new_price": "1190"}]).json()["assessment"]
    assert Decimal(a["result"]["relist_fees"]) > 0 and Decimal(a["result"]["net_profit"]) < Decimal(base["net_profit"])
    assert "UNVERIFIED_RULE:R8" in a["warnings"]


def test_loss_is_flagged(client):
    assert "LOSS" in ev(client, sell_price="1010").json()["assessment"]["warnings"]


def test_live_book_is_used_and_described(client, monkeypatch):
    seen = {}

    def fake(region, station, type_id):
        seen.update(region=region, station=station, type_id=type_id)
        return {"asks": [["1000", "500"]], "bids": [["1300", "500"]], "fetched_at": "2026-11-20T12:00:00Z", "cached": False}
    monkeypatch.setattr(finance_module, "fetch_station_book", fake)
    r = ev(client, type_id=34, use_live_book=True, buy_mode="IMMEDIATE", buy_price=None, sell_mode="IMMEDIATE", sell_price=None)
    body = r.json()
    assert seen == {"region": 10000002, "station": STATION, "type_id": 34}
    assert body["book"] == {"station_id": STATION, "station": "Jita IV - Moon 4 - Caldari Navy Assembly Plant",
                            "fetched_at": "2026-11-20T12:00:00Z", "cached": False, "ask_levels": 1, "bid_levels": 1}
    assert body["assessment"]["result"]["buy_price"] == "1000.00" and body["assessment"]["result"]["sell_price"] == "1300.00"


def test_each_market_uses_its_own_region_for_the_live_book(client, monkeypatch):
    seen = []
    monkeypatch.setattr(finance_module, "fetch_station_book",
                        lambda region, station, type_id: seen.append((region, station)) or
                        {"asks": [["1", "1"]], "bids": [["1", "1"]], "fetched_at": "x", "cached": True})
    for market, region, station in (("amarr", 10000043, 60008494), ("rens", 10000030, 60004588), ("hek", 10000042, 60005686),
                                    ("dodixie", 10000032, 60011866)):
        ev(client, market_id=market, type_id=1, use_live_book=True, buy_mode="IMMEDIATE", buy_price=None)
        assert seen[-1] == (region, station)


def test_live_book_failure_is_a_clean_503(client, monkeypatch):
    def down(*a):
        raise BookUnavailable("red")
    monkeypatch.setattr(finance_module, "fetch_station_book", down)
    r = ev(client, type_id=34, use_live_book=True, buy_mode="IMMEDIATE", buy_price=None)
    assert r.status_code == 503 and "red" not in r.text


@pytest.mark.parametrize("extra", [
    {"units": 0}, {"units": -5}, {"units": 1.5}, {"units": 10**13}, {"buy_price": "0"}, {"buy_price": "-1"},
    {"buy_price": "NaN"}, {"sell_price": "Infinity"}, {"buy_price": "1e14"}, {"market_id": "nowhere"},
    {"venue": "MOON"}, {"buy_mode": "MARKET"}, {"extra_field": 1}, {"owner_fee_percent": 21}, {"owner_fee_percent": -1},
    {"target_roi_percent": -100}, {"target_roi_percent": 1001}, {"available_capital": "-1"},
    {"profile_mode": "manual"}, {"profile_mode": "manual", "manual_profile": {"broker_relations": 6}},
    {"profile_mode": "manual", "manual_profile": {"corp_standing": 11}}, {"profile_mode": "default", "use_wallet": True},
    {"use_live_book": True}, {"use_live_book": True, "type_id": 34, "venue": "UPWELL"}, {"type_id": 0},
    {"relists": [{"side": "UP", "old_price": "1", "new_price": "2"}]},
    {"relists": [{"side": "SELL", "old_price": "0", "new_price": "2"}]},
    {"relists": [{"side": "SELL", "old_price": "1", "new_price": "2"}] * 21},
    {"asks": [["1", 1]] * 201}, {"asks": [["0", 1]]}, {"asks": [["1", 0]]}, {"bids": [["x", 1]]},
])
def test_invalid_input_is_rejected(client, extra):
    assert ev(client, **extra).status_code == 422


def test_unsafe_origin_is_refused(client):
    assert client.post("/api/finance/evaluate", json=BASE, headers={"Origin": "https://evil.example"}).status_code == 403
    two = {"scenarios": [{"name": "a", "request": BASE}, {"name": "b", "request": BASE}]}
    assert client.post("/api/finance/compare", json=two, headers={"Origin": "https://evil.example"}).status_code == 403


def test_profile_mine_needs_the_feature_and_a_session(client, tmp_path, monkeypatch):
    for name in ("EVE_LOGIN_CLIENT_ID", "EVE_LOGIN_CLIENT_SECRET", "USERS_ENC_KEYS"):
        monkeypatch.delenv(name, raising=False)
    assert ev(client, profile_mode="mine").status_code == 503
    from tests.test_profile import KEY
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.setenv("USERS_ENC_KEYS", KEY)
    monkeypatch.setenv("EVE_LOGIN_CLIENT_ID", "cid")
    monkeypatch.setenv("EVE_LOGIN_CLIENT_SECRET", "secret")
    users_db.init_users_db()
    assert ev(client, profile_mode="mine").status_code == 401


def test_profile_mine_uses_the_players_esi_profile_and_wallet(api):  # noqa: F811
    api.get("/api/me/profile")
    r = api.post("/api/finance/evaluate", json={**BASE, "profile_mode": "mine", "use_wallet": True})
    body = r.json()
    assert r.status_code == 200 and body["profile"]["mode"] == "mine" and body["profile"]["source"] == "ESI"
    assert body["profile"]["broker_relations"] == 5 and body["profile"]["accounting"] == 4
    assert Decimal(body["assessment"]["rates"]["broker_fee"]) == Decimal("0.0141")            # 3 − 1,5 − 0,09 (standing de facción 3)
    assert body["capital_source"] == "WALLET" and body["assessment"]["capital"]["available"] == "5000000.50"
    own = api.post("/api/finance/evaluate", json={**BASE, "profile_mode": "mine", "available_capital": "1000",
                                                  "use_wallet": True}).json()          # lo escrito a mano gana al wallet
    assert own["capital_source"] == "MANUAL" and own["assessment"]["capital"]["available"] == "1000.00"


def test_manual_corrections_flow_into_the_simulation(api):  # noqa: F811
    api.get("/api/me/profile")
    api.put("/api/me/profile/override", json={"skills": {"accounting": 5}})
    a = api.post("/api/finance/evaluate", json={**BASE, "profile_mode": "mine"}).json()["assessment"]
    assert Decimal(a["rates"]["sales_tax"]) == Decimal("0.03375")


# ---- /api/finance/compare -------------------------------------------------------------------------------------------

def test_compare_ranks_by_roi_and_skips_incomplete(client):
    body = {"scenarios": [
        {"name": "poco", "request": {**BASE, "sell_price": "1100"}},
        {"name": "mucho", "request": {**BASE, "sell_price": "1400"}},
        {"name": "roto", "request": {**BASE, "venue": "UPWELL"}},
    ]}
    r = client.post("/api/finance/compare", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["ranking"] == ["mucho", "poco"] and [x["name"] for x in out["results"]] == ["poco", "mucho", "roto"]
    assert out["results"][2]["assessment"]["calculation_status"] == "INCOMPLETE"


def test_compare_needs_two_to_six_named_scenarios(client):
    one = {"name": "a", "request": BASE}
    assert client.post("/api/finance/compare", json={"scenarios": [one]}).status_code == 422
    assert client.post("/api/finance/compare", json={"scenarios": [one] * 7}).status_code == 422
    assert client.post("/api/finance/compare", json={"scenarios": [one, {"name": "", "request": BASE}]}).status_code == 422
    assert client.post("/api/finance/compare", json={"scenarios": [one, {"name": "x" * 61, "request": BASE}]}).status_code == 422


# ---- Escenarios guardados ------------------------------------------------------------------------------------------

def test_scenarios_need_a_session(client, tmp_path, monkeypatch):
    for name in ("EVE_LOGIN_CLIENT_ID", "EVE_LOGIN_CLIENT_SECRET", "USERS_ENC_KEYS"):
        monkeypatch.delenv(name, raising=False)
    assert client.get("/api/me/scenarios").status_code == 503
    assert client.post("/api/me/scenarios", json={"name": "a", "request": BASE}).status_code == 503
    assert client.delete("/api/me/scenarios/1").status_code == 503


def live_book(monkeypatch):
    monkeypatch.setattr(finance_module, "fetch_station_book", lambda *a: {
        "asks": [["1000", "500"]], "bids": [["1300", "500"]], "fetched_at": "2026-11-20T12:00:00Z", "cached": False})


def test_a_saved_scenario_is_a_reproducible_snapshot(api, monkeypatch):  # noqa: F811
    api.get("/api/me/profile")
    live_book(monkeypatch)
    request = {**BASE, "type_id": 34, "buy_mode": "IMMEDIATE", "buy_price": None, "sell_mode": "IMMEDIATE", "sell_price": None,
               "profile_mode": "mine", "use_live_book": True}
    saved = api.post("/api/me/scenarios", json={"name": "  Tritanium  ", "request": request})
    assert saved.status_code == 201
    item = api.get("/api/me/scenarios").json()["scenarios"][0]
    assert item["name"] == "Tritanium" and item["id"] == saved.json()["id"] and item["engine_version"] and item["rules_version"]
    snap = item["request"]
    assert snap["use_live_book"] is False and snap["profile_mode"] == "manual" and snap["manual_profile"]["accounting"] == 4
    assert snap["asks"] == [["1000", 500]] and snap["bids"] == [["1300", 500]]
    assert item["meta"]["book"]["fetched_at"] == "2026-11-20T12:00:00Z" and item["meta"]["profile_mode"] == "mine"
    # El mundo cambia (otro libro, otras habilidades) y la foto sigue dando el mismo resultado.
    monkeypatch.setattr(finance_module, "fetch_station_book", lambda *a: {"asks": [["5", "1"]], "bids": [["5", "1"]], "fetched_at": "x", "cached": False})
    api.put("/api/me/profile/override", json={"skills": {"broker_relations": 0}})
    again = api.post("/api/finance/evaluate", json=snap).json()["assessment"]
    assert again["result"] == item["result"]["result"] and again["rates"] == item["result"]["rates"]


def test_wallet_capital_is_frozen_in_the_snapshot(api, monkeypatch):  # noqa: F811
    api.get("/api/me/profile")
    api.post("/api/me/scenarios", json={"name": "w", "request": {**BASE, "profile_mode": "mine", "use_wallet": True}})
    snap = api.get("/api/me/scenarios").json()["scenarios"][0]["request"]
    assert snap["use_wallet"] is False and snap["available_capital"] == "5000000.50"


def test_scenarios_can_be_deleted_only_by_their_owner(api):  # noqa: F811
    sid = api.post("/api/me/scenarios", json={"name": "a", "request": BASE}).json()["id"]
    conn = users_db.connect()
    users_db.upsert_user(conn, 777, "Other", "x", users_db.utcnow())
    other = users_db.add_scenario(conn, 777, "theirs", {"request": {}}, {}, "1", "1", users_db.utcnow())
    conn.commit()
    conn.close()
    assert api.delete(f"/api/me/scenarios/{other}").status_code == 404
    assert api.delete(f"/api/me/scenarios/{sid}").status_code == 200
    assert api.delete(f"/api/me/scenarios/{sid}").status_code == 404
    assert api.get("/api/me/scenarios").json()["scenarios"] == []
    conn = users_db.connect()
    assert users_db.count_scenarios(conn, 777) == 1
    conn.close()


def test_scenarios_are_listed_only_for_their_owner(api):  # noqa: F811
    conn = users_db.connect()
    users_db.upsert_user(conn, 777, "Other", "x", users_db.utcnow())
    users_db.add_scenario(conn, 777, "theirs", {"request": {}}, {}, "1", "1", users_db.utcnow())
    conn.commit()
    conn.close()
    assert api.get("/api/me/scenarios").json()["scenarios"] == []


def test_scenario_limit_per_player(api, monkeypatch):  # noqa: F811
    monkeypatch.setattr(users_db, "MAX_SCENARIOS", 2)
    for i in range(2):
        assert api.post("/api/me/scenarios", json={"name": f"s{i}", "request": BASE}).status_code == 201
    r = api.post("/api/me/scenarios", json={"name": "extra", "request": BASE})
    assert r.status_code == 409 and len(api.get("/api/me/scenarios").json()["scenarios"]) == 2


def test_saving_checks_origin_and_input(api):  # noqa: F811
    evil = {"Origin": "https://evil.example"}
    assert api.post("/api/me/scenarios", json={"name": "a", "request": BASE}, headers=evil).status_code == 403
    assert api.delete("/api/me/scenarios/1", headers=evil).status_code == 403
    assert api.post("/api/me/scenarios", json={"name": "", "request": BASE}).status_code == 422
    assert api.post("/api/me/scenarios", json={"name": "a", "request": {**BASE, "units": 0}}).status_code == 422


def test_export_includes_scenarios_and_delete_account_removes_them(api):  # noqa: F811
    api.post("/api/me/scenarios", json={"name": "a", "request": BASE})
    data = api.get("/api/auth/me/export").json()
    assert [s["name"] for s in data["scenarios"]] == ["a"] and "refresh_token_enc" not in json.dumps(data)
    api.delete("/api/auth/me")
    conn = users_db.connect()
    assert conn.execute("SELECT COUNT(*) FROM financial_scenario").fetchone()[0] == 0
    conn.close()


def test_schema_is_version_4_and_upgrades_an_existing_v2_file(tmp_path):
    path = str(tmp_path / "old.db")
    conn = users_db.connect(path)
    conn.executescript(users_db.SCHEMA.split("CREATE TABLE IF NOT EXISTS financial_scenario")[0])
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    users_db.init_users_db(path)
    conn = users_db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4 == users_db.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM financial_scenario").fetchone()[0] == 0
    conn.close()


def test_an_existing_v3_profile_table_gets_the_order_columns_without_losing_data(tmp_path):
    path = str(tmp_path / "v3.db")
    conn = users_db.connect(path)
    conn.executescript("""
        CREATE TABLE user (character_id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, consent_version TEXT NOT NULL, consent_at TEXT NOT NULL);
        CREATE TABLE user_profile (character_id INTEGER PRIMARY KEY REFERENCES user(character_id) ON DELETE CASCADE,
            skills_json TEXT, skills_at TEXT, standings_json TEXT, standings_at TEXT, wallet_isk TEXT, wallet_at TEXT,
            override_json TEXT, sync_status TEXT NOT NULL DEFAULT 'NEVER', last_attempt_at TEXT);
        INSERT INTO user VALUES (1, 'P', 'a', 'a', 'v', 'a');
        INSERT INTO user_profile (character_id, wallet_isk) VALUES (1, '42.00');
    """)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()
    users_db.init_users_db(path)
    users_db.init_users_db(path)                       # repetir no falla: las columnas ya existen
    conn = users_db.connect(path)
    row = users_db.get_profile(conn, 1)
    assert row["wallet_isk"] == "42.00" and row["committed_isk"] is None and row["orders_at"] is None
    conn.close()
