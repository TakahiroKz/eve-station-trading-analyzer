"""Esquema por mercado (market_id en la clave): semilla de mercados, migración desde el esquema de
un solo mercado, mercados que conviven sin mezclarse, y la API con el parámetro `market`."""
import sqlite3

import pytest

import storage.db as storage_db
from scheduler.run import screen_opportunities
from storage.db import (
    MARKETS_SEED,
    drop_pre_market_tables,
    get_connection,
    get_item_status,
    init_db,
    insert_status_history,
    pre_market_tables,
    prune_old_snapshots,
    upsert_item_status,
    upsert_market_history,
    upsert_market_snapshot,
)
from tests.conftest import seed_item

LEGACY_SCHEMA = """
CREATE TABLE item_type (type_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE market_history (
    type_id INTEGER NOT NULL, date TEXT NOT NULL, avg_price REAL NOT NULL, highest REAL NOT NULL,
    lowest REAL NOT NULL, volume INTEGER NOT NULL, order_count INTEGER NOT NULL,
    PRIMARY KEY (type_id, date), FOREIGN KEY (type_id) REFERENCES item_type(type_id));
CREATE TABLE market_snapshot (
    type_id INTEGER NOT NULL, captured_at TEXT NOT NULL, best_buy REAL, best_sell REAL,
    buy_volume INTEGER, sell_volume INTEGER, buy_order_count INTEGER NOT NULL DEFAULT 0,
    sell_order_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (type_id, captured_at));
CREATE TABLE opportunity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type_id INTEGER NOT NULL, evaluated_at TEXT NOT NULL,
    buy REAL NOT NULL, sell REAL NOT NULL, volumen_deseado REAL NOT NULL, volumen_diario_real REAL NOT NULL,
    beneficio REAL NOT NULL, spread_bruto REAL NOT NULL, precio_min_venta REAL NOT NULL, roi REAL NOT NULL,
    evaluacion_spread TEXT NOT NULL, posicion_vs_volumen REAL NOT NULL, liquidez TEXT NOT NULL,
    recomendacion TEXT NOT NULL);
CREATE TABLE item_status (
    type_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('POTENCIAL', 'POTENCIAL_SIN_ORDENES', 'DESCARTADO', 'EN_OBSERVACION')),
    reason TEXT NOT NULL, spread_bruto REAL NOT NULL, evaluacion_spread TEXT NOT NULL, liquidez TEXT NOT NULL,
    roi REAL NOT NULL, best_buy REAL NOT NULL DEFAULT 0, best_sell REAL NOT NULL DEFAULT 0,
    volumen_diario_real REAL NOT NULL DEFAULT 0, buy_order_count INTEGER NOT NULL DEFAULT 0,
    sell_order_count INTEGER NOT NULL DEFAULT 0, avg_daily_volume_7d REAL NOT NULL DEFAULT 0,
    avg_daily_order_count_7d REAL NOT NULL DEFAULT 0, last_evaluated_at TEXT NOT NULL);
CREATE TABLE item_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, type_id INTEGER NOT NULL, previous_status TEXT,
    new_status TEXT NOT NULL, changed_at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE INDEX idx_history_type ON market_history(type_id);
CREATE INDEX idx_snapshot_type ON market_snapshot(type_id);
CREATE INDEX idx_opportunity_type ON opportunity_log(type_id);
CREATE INDEX idx_status_history_type ON item_status_history(type_id);
"""


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany("INSERT INTO item_type VALUES (?, ?)", [(34, "Tritanium"), (35, "Pyerite")])
    conn.executemany(
        "INSERT INTO market_history VALUES (?, ?, 4.0, 4.5, 3.5, 100, 5)",
        [(34, "2026-11-01"), (34, "2026-11-02"), (35, "2026-11-01")],
    )
    conn.executemany(
        "INSERT INTO market_snapshot VALUES (?, ?, 4.0, 4.5, 10, 20, 2, 3)",
        [(34, "2026-11-02T10:00:00+00:00"), (35, "2026-11-02T10:00:00+00:00")],
    )
    conn.executemany(
        "INSERT INTO opportunity_log (id, type_id, evaluated_at, buy, sell, volumen_deseado, volumen_diario_real, "
        "beneficio, spread_bruto, precio_min_venta, roi, evaluacion_spread, posicion_vs_volumen, liquidez, "
        "recomendacion) VALUES (?, ?, ?, 4, 4.5, 1, 1, 0.3, 0.1, 4.2, 0.1, 'ok', 0.1, 'ok', 'ok')",
        [(7, 34, "2026-11-02T10:00:00+00:00"), (9, 35, "2026-11-02T11:00:00+00:00")],
    )
    conn.executemany(
        "INSERT INTO item_status VALUES (?, 'POTENCIAL', 'ok', 0.1, 'ok', 'alta', 0.2, 4, 4.5, 1000, 3, 3, 900, 20, "
        "'2026-11-02T10:00:00+00:00')",
        [(34,), (35,)],
    )
    conn.execute(
        "INSERT INTO item_status_history (id, type_id, previous_status, new_status, changed_at, reason) "
        "VALUES (5, 34, NULL, 'POTENCIAL', '2026-11-02T10:00:00+00:00', 'ok')"
    )
    conn.commit()
    conn.close()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ---------------- semilla de mercados ----------------
def test_init_db_creates_the_market_table_with_the_five_hubs(tmp_path):
    path = str(tmp_path / "m.db")
    init_db(path)
    conn = get_connection(path)
    rows = {r["market_id"]: dict(r) for r in conn.execute("SELECT * FROM market")}
    conn.close()

    assert list(rows) == [m[0] for m in MARKETS_SEED] or set(rows) == {"jita", "amarr", "dodixie", "rens", "hek"}
    assert rows["jita"]["region_id"] == 10000002 and rows["jita"]["enabled"] == 1
    assert rows["amarr"]["region_id"] == 10000043 and rows["amarr"]["system_id"] == 30002187
    assert all(rows[m]["enabled"] == 0 for m in ("amarr", "dodixie", "rens", "hek"))
    assert all(r["kind"] == "region" for r in rows.values())


def test_reseeding_refreshes_names_but_keeps_the_enabled_flag(tmp_path):
    path = str(tmp_path / "m.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("UPDATE market SET enabled = 1, name = 'viejo' WHERE market_id = 'amarr'")
    conn.commit()
    conn.close()

    init_db(path)

    conn = get_connection(path)
    row = conn.execute("SELECT name, enabled FROM market WHERE market_id = 'amarr'").fetchone()
    conn.close()
    assert (row["name"], row["enabled"]) == ("Amarr", 1)


# ---------------- migración ----------------
def test_the_migration_moves_every_legacy_row_under_jita_and_keeps_the_ids(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path)

    init_db(path)

    conn = get_connection(path)
    for table, expected in (("market_history", 3), ("market_snapshot", 2), ("opportunity_log", 2),
                            ("item_status", 2), ("item_status_history", 1)):
        assert _count(conn, table) == expected, table
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE market_id != 'jita'").fetchone()[0] == 0
    assert [r[0] for r in conn.execute("SELECT id FROM opportunity_log ORDER BY id")] == [7, 9]
    assert conn.execute("SELECT id FROM item_status_history").fetchone()[0] == 5
    assert get_item_status(conn, 34)["status"] == "POTENCIAL"
    assert set(pre_market_tables(conn)) == {
        "market_history", "market_snapshot", "item_status", "item_status_history", "opportunity_log",
    }
    conn.close()


def test_after_the_migration_two_markets_can_hold_the_same_item_and_date(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path)
    init_db(path)
    conn = get_connection(path)

    upsert_market_history(
        conn, 34, {"date": "2026-11-01", "average": 9.0, "highest": 9.5, "lowest": 8.5, "volume": 7, "order_count": 2},
        market_id="amarr",
    )
    conn.commit()

    rows = {r["market_id"]: r["avg_price"] for r in conn.execute(
        "SELECT market_id, avg_price FROM market_history WHERE type_id = 34 AND date = '2026-11-01'")}
    conn.close()
    assert rows == {"jita": 4.0, "amarr": 9.0}


def test_the_migration_is_idempotent_and_the_old_copies_can_be_dropped(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path)
    init_db(path)
    init_db(path)  # segunda corrida: no hace nada

    conn = get_connection(path)
    assert _count(conn, "market_history") == 3
    dropped = drop_pre_market_tables(conn)
    assert len(dropped) == 5 and pre_market_tables(conn) == []
    assert _count(conn, "market_history") == 3
    conn.close()


def test_a_failure_during_the_migration_rolls_everything_back(tmp_path, monkeypatch):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path)

    def boom(conn):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(storage_db, "_seed_markets", boom)
    with pytest.raises(RuntimeError):
        init_db(path)

    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(item_status)")]
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "market_id" not in cols  # sigue el esquema anterior
    assert not any(n.endswith("_pre_market") for n in names)
    assert conn.execute("SELECT COUNT(*) FROM market_history").fetchone()[0] == 3
    conn.close()


# ---------------- mercados que conviven ----------------
@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "mm.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.commit()
    yield conn
    conn.close()


def _status(status, buy):
    return {
        "type_id": 34, "status": status, "reason": "ok", "spread_bruto": 0.1, "evaluacion_spread": "ok",
        "liquidez": "alta", "roi": 0.2, "best_buy": buy, "best_sell": buy + 1, "volumen_diario_real": 10,
        "buy_order_count": 1, "sell_order_count": 1, "avg_daily_volume_7d": 5, "avg_daily_order_count_7d": 5,
        "last_evaluated_at": "2026-11-18T00:00:00+00:00",
    }


def test_each_market_keeps_its_own_status_for_the_same_item(db):
    upsert_item_status(db, _status("POTENCIAL", 4.0), market_id="jita")
    upsert_item_status(db, _status("DESCARTADO", 9.0), market_id="amarr")
    insert_status_history(db, 34, None, "DESCARTADO", "2026-11-18T00:00:00+00:00", "x", market_id="amarr")
    db.commit()

    assert get_item_status(db, 34, market_id="jita")["status"] == "POTENCIAL"
    assert get_item_status(db, 34, market_id="amarr")["best_buy"] == 9.0
    assert get_item_status(db, 34)["status"] == "POTENCIAL"  # el mercado por defecto es jita
    assert db.execute("SELECT COUNT(*) FROM item_status_history WHERE market_id = 'jita'").fetchone()[0] == 0


def test_pruning_snapshots_only_touches_the_given_market(db):
    old = "2020-01-01T00:00:00+00:00"
    for market in ("jita", "amarr"):
        upsert_market_snapshot(db, 34, old, {"best_buy": 1.0, "best_sell": 2.0}, market_id=market)
    db.commit()

    deleted = prune_old_snapshots(db, keep_hours=6, market_id="amarr")

    left = [r["market_id"] for r in db.execute("SELECT market_id FROM market_snapshot")]
    assert deleted == 1 and left == ["jita"]


def test_the_screening_of_one_market_uses_only_its_own_prices_and_leaves_the_others(tmp_path, monkeypatch):
    path = str(tmp_path / "scr.db")
    init_db(path)
    c = get_connection(path)
    c.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    for market, buy, sell in (("jita", 4.0, 4.5), ("amarr", 8.0, 9.5)):
        c.execute(
            "INSERT INTO market_snapshot (market_id, type_id, captured_at, best_buy, best_sell, buy_volume, "
            "sell_volume, buy_order_count, sell_order_count) VALUES (?, 34, datetime('now'), ?, ?, 1000, 1000, 3, 3)",
            (market, buy, sell),
        )
        c.execute(
            "INSERT INTO market_history (market_id, type_id, date, avg_price, highest, lowest, volume, order_count) "
            "VALUES (?, 34, date('now'), ?, ?, ?, 1000, 5)", (market, buy + 0.2, sell, buy),
        )
    c.commit()
    c.close()
    monkeypatch.setattr("scheduler.run.get_current_wallet_balance", lambda: 5_000_000.0)
    monkeypatch.setattr("scheduler.run.dispatch", lambda events: None)
    monkeypatch.setattr("scheduler.run.is_price_sane", lambda *a, **k: True)
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "ok"))

    screen_opportunities(path, str(tmp_path / "r.xlsx"), market_id="amarr")

    c = get_connection(path)
    amarr = get_item_status(c, 34, market_id="amarr")
    jita = get_item_status(c, 34, market_id="jita")
    logged = [r["market_id"] for r in c.execute("SELECT market_id FROM opportunity_log")]
    c.close()
    assert amarr["best_buy"] == 8.0 and jita is None  # Jita no se tocó
    assert logged == ["amarr"]


# ---------------- API ----------------
def _enable_amarr(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = 'amarr'")
    conn.execute(
        "INSERT INTO item_status (market_id, type_id, status, reason, spread_bruto, evaluacion_spread, liquidez, "
        "roi, best_buy, best_sell, volumen_diario_real, last_evaluated_at) "
        "VALUES ('amarr', 34, 'DESCARTADO', 'ok', 0.1, 'buena', 'alta', 0.2, 9.0, 9.5, 50, datetime('now'))"
    )
    conn.commit()
    conn.close()


def test_the_api_defaults_to_jita_and_can_read_another_market(client):
    api, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium", status="POTENCIAL")
    _enable_amarr(db_path)

    jita = api.get("/api/items").json()
    amarr = api.get("/api/items", params={"market": "amarr"}).json()

    assert jita["total"] == 1 and jita["items"][0]["status"] == "POTENCIAL" and jita["items"][0]["best_buy"] == 4.0
    assert amarr["total"] == 1 and amarr["items"][0]["status"] == "DESCARTADO" and amarr["items"][0]["best_buy"] == 9.0
    assert api.get("/api/summary").json()["counts"] == {"POTENCIAL": 1}
    assert api.get("/api/summary", params={"market": "amarr"}).json()["counts"] == {"DESCARTADO": 1}
    assert api.get("/api/items/34", params={"market": "amarr"}).json()["status"]["best_buy"] == 9.0
    assert api.get("/api/items/34").json()["status"]["best_buy"] == 4.0


def test_the_api_rejects_unknown_and_disabled_markets(client):
    api, _ = client

    assert api.get("/api/items", params={"market": "nope"}).status_code == 404
    assert api.get("/api/items", params={"market": "amarr"}).status_code == 404  # existe pero no está activo
    assert api.get("/api/summary", params={"market": "hek"}).status_code == 404
    assert api.get("/api/items/34", params={"market": "rens"}).status_code == 404
    assert api.get("/api/status-changes", params={"market": "dodixie"}).status_code == 404
    assert api.get("/api/items").status_code == 200


def test_status_changes_are_filtered_by_market(client):
    api, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    _enable_amarr(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO item_status_history (market_id, type_id, previous_status, new_status, changed_at, reason) "
        "VALUES ('jita', 34, NULL, 'POTENCIAL', datetime('now'), 'a'), "
        "('amarr', 34, NULL, 'DESCARTADO', datetime('now'), 'b')"
    )
    conn.commit()
    conn.close()

    jita = api.get("/api/status-changes").json()
    amarr = api.get("/api/status-changes", params={"market": "amarr"}).json()

    assert [c["new_status"] for c in jita] == ["POTENCIAL"]
    assert [c["new_status"] for c in amarr] == ["DESCARTADO"]


# ---------------- /api/markets, categorías y recomendación por mercado ----------------
def test_markets_endpoint_lists_only_enabled_markets_with_their_counts(client):
    api, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium", status="POTENCIAL")
    seed_item(db_path, type_id=35, name="Pyerite", status="DESCARTADO")

    only_jita = api.get("/api/markets").json()
    assert [m["market_id"] for m in only_jita] == ["jita"]
    assert only_jita[0]["name"] == "Jita" and only_jita[0]["region_id"] == 10000002
    assert only_jita[0]["counts"] == {"POTENCIAL": 1, "DESCARTADO": 1} and only_jita[0]["total"] == 2
    assert only_jita[0]["last_evaluated_at"] is not None

    _enable_amarr(db_path)
    both = api.get("/api/markets").json()
    assert [m["market_id"] for m in both] == ["jita", "amarr"]
    assert both[1]["counts"] == {"DESCARTADO": 1} and both[1]["total"] == 1


def test_an_enabled_market_without_data_is_listed_empty(client):
    api, db_path = client
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = 'hek'")
    conn.commit()
    conn.close()

    hek = [m for m in api.get("/api/markets").json() if m["market_id"] == "hek"][0]

    assert hek["counts"] == {} and hek["total"] == 0 and hek["last_evaluated_at"] is None


def test_categories_only_list_what_exists_in_the_chosen_market(client):
    api, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium", category_id=4, category_name="Material")
    seed_item(db_path, type_id=35, name="Rifter", category_id=6, category_name="Ship")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = 'amarr'")
    conn.execute(
        "INSERT INTO item_status (market_id, type_id, status, reason, spread_bruto, evaluacion_spread, liquidez, "
        "roi, last_evaluated_at) VALUES ('amarr', 34, 'POTENCIAL', 'ok', 0.1, 'ok', 'alta', 0.2, datetime('now'))"
    )
    conn.commit()
    conn.close()

    jita = {c["category_name"] for c in api.get("/api/categories").json()}
    amarr = {c["category_name"] for c in api.get("/api/categories", params={"market": "amarr"}).json()}

    assert jita == {"Material", "Ship"} and amarr == {"Material"}
    assert api.get("/api/categories", params={"market": "nope"}).status_code == 404


def test_the_live_recommendation_uses_the_chosen_markets_prices(client):
    from tests.conftest import FAKE_CF_HEADER

    api, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium", status="POTENCIAL")
    _enable_amarr(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO market_snapshot (market_id, type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) VALUES ('amarr', 34, datetime('now'), 9.0, 9.5, 5, 5, 1, 1)"
    )
    conn.commit()
    conn.close()

    jita = api.get("/api/private/items/34/recommendation", headers=FAKE_CF_HEADER).json()
    amarr = api.get("/api/private/items/34/recommendation", params={"market": "amarr"}, headers=FAKE_CF_HEADER).json()

    assert (jita["buy"], amarr["buy"]) == (4.0, 9.0)
    unknown = api.get("/api/private/items/34/recommendation", params={"market": "nope"}, headers=FAKE_CF_HEADER)
    assert unknown.status_code == 404
