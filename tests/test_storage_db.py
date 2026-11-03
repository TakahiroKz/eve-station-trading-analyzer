"""Cobertura dedicada de storage/db.py (D4): migraciones idempotentes, el seed de
defaults desde storage/settings_registry.py, y el CRUD de app_settings. El resto de
los helpers de storage/db.py (upsert_market_snapshot, upsert_item_status, etc.) ya
quedan ejercitados indirectamente por tests/test_scheduler_run.py y
tests/test_orders_run.py -- acá se agregan un par de tests directos para los que
todavía no tenían ninguno."""
import sqlite3

import pytest

from storage.db import (
    _migrate_classification_settings,
    _migrate_schema,
    get_app_settings,
    get_app_settings_dict,
    get_cached_group,
    get_connection,
    init_db,
    reset_app_settings,
    update_app_setting,
    upsert_item_type,
)
from storage.settings_registry import SETTINGS


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


# ---------- init_db / seed de defaults ----------

def test_init_db_seeds_every_setting_from_the_registry(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    rows = {r["key"]: r["value"] for r in get_app_settings(conn)}
    conn.close()

    assert rows == {s.key: s.default_value for s in SETTINGS}


def test_init_db_is_idempotent_and_does_not_overwrite_edited_values(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    update_app_setting(conn, "min_daily_volume_7d", 999)
    conn.close()

    # Segunda corrida (ej. el motor arrancando de nuevo) no debería pisar el valor
    # editado por el usuario -- _seed_defaults() usa INSERT OR IGNORE para `value`.
    init_db(db_path)

    conn = get_connection(db_path)
    row = next(r for r in get_app_settings(conn) if r["key"] == "min_daily_volume_7d")
    conn.close()
    assert row["value"] == 999
    assert row["default_value"] == 10.0  # el default sí se refresca desde el registro


# ---------- migraciones ----------

def test_migrate_schema_adds_missing_market_snapshot_order_count_columns(db_path):
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE market_snapshot (type_id INTEGER, captured_at TEXT, best_buy REAL, "
        "best_sell REAL, buy_volume INTEGER, sell_volume INTEGER)",
    )
    conn.commit()

    _migrate_schema(conn)

    columns = {r["name"] for r in conn.execute("PRAGMA table_info(market_snapshot)").fetchall()}
    conn.close()
    assert {"buy_order_count", "sell_order_count"} <= columns


def test_migrate_schema_drops_item_status_missing_the_new_check_constraint(db_path):
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE item_status (type_id INTEGER PRIMARY KEY, "
        "status TEXT CHECK (status IN ('POTENCIAL', 'DESCARTADO')))",
    )
    conn.commit()

    _migrate_schema(conn)

    remaining = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='item_status'",
    ).fetchone()
    conn.close()
    # _migrate_schema() solo dropea -- init_db() la recrea después vía schema.sql
    # (CREATE TABLE IF NOT EXISTS), ya cubierto por test_init_db_is_idempotent_*.
    assert remaining is None


def test_migrate_schema_adds_missing_character_order_columns(db_path):
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE character_order (order_id INTEGER PRIMARY KEY, type_id INTEGER, "
        "region_id INTEGER, is_buy_order INTEGER, price REAL, volume_remain INTEGER, "
        "volume_total INTEGER, issued TEXT, is_undercut INTEGER, undercut_alerted INTEGER, "
        "first_seen_at TEXT, last_seen_at TEXT)",
    )
    conn.commit()

    _migrate_schema(conn)

    columns = {r["name"] for r in conn.execute("PRAGMA table_info(character_order)").fetchall()}
    conn.close()
    assert {"orders_ahead", "price_gap", "best_price"} <= columns


def test_migrate_schema_is_a_no_op_on_a_freshly_initialized_db(db_path):
    init_db(db_path)  # ya corre schema.sql completo, con todas las columnas al día
    conn = get_connection(db_path)
    _migrate_schema(conn)  # no debería fallar ni duplicar columnas
    columns = [r["name"] for r in conn.execute("PRAGMA table_info(character_order)").fetchall()]
    conn.close()
    assert columns.count("orders_ahead") == 1


def test_migrate_classification_settings_transfers_values_and_drops_the_old_table(db_path):
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE classification_settings (id INTEGER PRIMARY KEY, "
        "min_daily_volume_7d REAL, min_daily_order_count_7d REAL)",
    )
    conn.execute(
        "INSERT INTO classification_settings (id, min_daily_volume_7d, min_daily_order_count_7d) "
        "VALUES (1, 123.0, 7.0)",
    )
    # app_settings tiene que existir para el INSERT OR REPLACE de la migración.
    conn.executescript(
        "CREATE TABLE app_settings (key TEXT PRIMARY KEY, category TEXT, label TEXT, "
        "description TEXT, value REAL, default_value REAL, updated_at TEXT);",
    )
    conn.commit()

    _migrate_classification_settings(conn)
    conn.commit()

    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'min_daily_volume_7d'",
    ).fetchone()
    dropped = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='classification_settings'",
    ).fetchone()
    conn.close()

    assert row["value"] == 123.0  # el valor viejo del usuario, no el default del registro
    assert dropped is None


def test_migrate_classification_settings_is_a_no_op_without_the_old_table(db_path):
    init_db(db_path)  # nunca tuvo classification_settings
    conn = get_connection(db_path)
    _migrate_classification_settings(conn)  # no debería fallar
    conn.close()


# ---------- CRUD de app_settings ----------

def test_get_app_settings_dict_maps_key_to_value(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    settings = get_app_settings_dict(conn)
    conn.close()
    assert settings["min_daily_order_count_7d"] == 3.0


def test_update_app_setting_persists_the_new_value(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    update_app_setting(conn, "min_daily_volume_7d", 55)
    conn.close()

    conn = get_connection(db_path)
    assert get_app_settings_dict(conn)["min_daily_volume_7d"] == 55
    conn.close()


def test_update_app_setting_raises_keyerror_for_an_unknown_key(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    with pytest.raises(KeyError):
        update_app_setting(conn, "no_existe", 1)
    conn.close()


def test_reset_app_settings_restores_every_default_value(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    update_app_setting(conn, "min_daily_volume_7d", 55)
    update_app_setting(conn, "min_daily_order_count_7d", 9)

    reset_app_settings(conn)

    settings = get_app_settings_dict(conn)
    conn.close()
    assert settings["min_daily_volume_7d"] == 10.0
    assert settings["min_daily_order_count_7d"] == 3.0


def test_reset_app_settings_with_explicit_keys_only_resets_those(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    update_app_setting(conn, "min_daily_volume_7d", 55)
    update_app_setting(conn, "min_daily_order_count_7d", 9)

    reset_app_settings(conn, keys=["min_daily_volume_7d"])

    settings = get_app_settings_dict(conn)
    conn.close()
    assert settings["min_daily_volume_7d"] == 10.0
    assert settings["min_daily_order_count_7d"] == 9  # no estaba en la lista, no se tocó


# ---------- un par de helpers CRUD directos que no tenían test propio ----------

def test_upsert_item_type_updates_the_name_on_conflict(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    upsert_item_type(conn, 34, "Tritanium")
    upsert_item_type(conn, 34, "Tritanium (renombrado)")
    conn.commit()

    name = conn.execute("SELECT name FROM item_type WHERE type_id = 34").fetchone()["name"]
    conn.close()
    assert name == "Tritanium (renombrado)"


def test_get_cached_group_returns_none_when_the_group_was_never_cached(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    assert get_cached_group(conn, 999) is None
    conn.close()


def test_get_connection_enforces_foreign_keys(db_path):
    init_db(db_path)
    conn = get_connection(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        # market_history referencia item_type -- no debería poder insertarse un
        # type_id que no existe todavía.
        conn.execute(
            "INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, "
            "order_count) VALUES (999999, date('now'), 1, 1, 1, 1, 1)",
        )
    conn.close()


def test_prune_old_snapshots_keeps_recent_rows_and_reports_deleted_count(tmp_path):
    from storage.db import prune_old_snapshots

    path = str(tmp_path / "prune.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    for days_ago in (0, 3, 10, 20):
        conn.execute(
            "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, "
            "sell_volume, buy_order_count, sell_order_count) "
            f"VALUES (34, datetime('now', '-{days_ago} days'), 1, 2, 1, 1, 1, 1)",
        )
    conn.commit()

    deleted = prune_old_snapshots(conn, keep_days=7)
    remaining = conn.execute("SELECT COUNT(*) FROM market_snapshot").fetchone()[0]
    conn.close()

    assert deleted == 2
    assert remaining == 2
