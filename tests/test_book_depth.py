"""Profundidad del libro de órdenes: cálculo, persistencia en market_snapshot y API del detalle."""
import sqlite3
import time

import pytest

from analytics.market_aggregation import DEPTH_BAND, build_orders_by_type
from storage.db import get_connection, init_db, upsert_market_snapshot
from tests.conftest import seed_item


def order(price, volume, buy, type_id=34):
    return {"type_id": type_id, "is_buy_order": buy, "price": price, "volume_remain": volume}


def test_depth_counts_the_units_within_five_percent_of_the_best_price():
    orders = [
        order(100.0, 10, True), order(96.0, 20, True), order(95.0, 30, True), order(94.9, 500, True),  # compra
        order(110.0, 5, False), order(115.0, 7, False), order(115.6, 900, False),                      # venta
    ]
    entry = build_orders_by_type(orders)[34]

    assert DEPTH_BAND == 0.05
    assert entry["buy_depth_5pct"] == 10 + 20 + 30        # 95,0 entra (límite incluido); 94,9 no
    assert entry["sell_depth_5pct"] == 5 + 7              # 115,5 es el límite: 115,6 queda fuera


def test_gap_is_the_distance_to_the_next_price_level_in_basis_points():
    orders = [order(100.0, 10, True), order(100.0, 5, True), order(98.0, 40, True),
              order(200.0, 3, False), order(210.0, 3, False)]
    entry = build_orders_by_type(orders)[34]

    assert entry["buy_gap_bp"] == 200      # 100 -> 98 = 2 %
    assert entry["sell_gap_bp"] == 500     # 200 -> 210 = 5 %


def test_top_share_is_the_part_of_the_volume_sitting_at_the_best_price():
    orders = [order(100.0, 30, True), order(100.0, 10, True), order(90.0, 60, True)]
    entry = build_orders_by_type(orders)[34]

    assert entry["buy_top_permille"] == 400   # 40 de 100 unidades


def test_a_side_without_a_second_level_has_no_gap_and_an_empty_side_has_no_depth_at_all():
    entry = build_orders_by_type([order(100.0, 10, True), order(100.0, 5, True)])[34]

    assert entry["buy_gap_bp"] is None and entry["buy_top_permille"] == 1000
    assert entry["sell_depth_5pct"] is None and entry["sell_gap_bp"] is None and entry["sell_top_permille"] is None


def test_depth_is_computed_per_type_and_per_side_without_mixing():
    orders = [order(100.0, 10, True, type_id=34), order(50.0, 99, True, type_id=35), order(55.0, 1, False, type_id=35)]
    by_type = build_orders_by_type(orders)

    assert by_type[34]["buy_depth_5pct"] == 10 and by_type[35]["buy_depth_5pct"] == 99
    assert by_type[35]["sell_depth_5pct"] == 1 and by_type[34]["sell_depth_5pct"] is None


def test_the_basic_fields_are_unchanged():
    entry = build_orders_by_type([order(5.0, 100, True), order(5.5, 50, True), order(6.0, 200, False)])[34]

    assert (entry["best_buy"], entry["best_sell"], entry["buy_volume"], entry["sell_volume"]) == (5.5, 6.0, 150, 200)
    assert (entry["buy_order_count"], entry["sell_order_count"]) == (2, 1)


def test_a_region_sized_book_is_aggregated_quickly():
    # ~400 mil órdenes (el tamaño de The Forge): el ciclo de precios no debe notar el cálculo de profundidad.
    orders = [order(100.0 + (i % 50) * 0.1, 1 + i % 20, i % 2 == 0, type_id=i % 17000) for i in range(400_000)]
    start = time.perf_counter()
    result = build_orders_by_type(orders)
    elapsed = time.perf_counter() - start

    assert len(result) == 17000
    assert elapsed < 6.0, f"build_orders_by_type tardó {elapsed:.1f}s"


def test_snapshot_round_trip_keeps_the_depth_columns(tmp_path):
    db_path = str(tmp_path / "depth.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    entry = build_orders_by_type([order(100.0, 30, True), order(98.0, 10, True), order(110.0, 5, False)])[34]

    upsert_market_snapshot(conn, 34, "2026-11-19T10:00:00+00:00", entry)
    upsert_market_snapshot(conn, 34, "2026-11-19T10:00:00+00:00", entry)  # idempotente
    row = conn.execute("SELECT * FROM market_snapshot").fetchone()
    conn.close()

    assert (row["buy_depth_5pct"], row["sell_depth_5pct"]) == (40, 5)
    assert (row["buy_gap_bp"], row["sell_gap_bp"]) == (200, None)
    assert (row["buy_top_permille"], row["sell_top_permille"]) == (750, 1000)


def test_a_snapshot_without_depth_data_stores_nulls(tmp_path):
    db_path = str(tmp_path / "old.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    upsert_market_snapshot(conn, 34, "2026-11-19T10:00:00+00:00", {"best_buy": 4.0, "best_sell": 4.5})
    row = conn.execute("SELECT buy_depth_5pct, sell_gap_bp FROM market_snapshot").fetchone()
    conn.close()

    assert row["buy_depth_5pct"] is None and row["sell_gap_bp"] is None


def test_migration_adds_the_depth_columns_to_an_existing_database(tmp_path):
    db_path = str(tmp_path / "pre.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    for column in ("buy_depth_5pct", "sell_depth_5pct", "buy_gap_bp", "sell_gap_bp",
                   "buy_top_permille", "sell_top_permille"):
        conn.execute(f"ALTER TABLE market_snapshot DROP COLUMN {column}")
    conn.commit()
    conn.close()

    init_db(db_path)
    init_db(db_path)  # idempotente

    conn = sqlite3.connect(db_path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(market_snapshot)")}
    conn.close()
    assert {"buy_depth_5pct", "sell_depth_5pct", "buy_gap_bp", "sell_gap_bp",
            "buy_top_permille", "sell_top_permille"} <= columns


def test_the_item_detail_exposes_the_latest_snapshot_depth(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market_snapshot SET buy_depth_5pct = 1200, sell_depth_5pct = 800, buy_gap_bp = 35, "
                 "buy_top_permille = 420 WHERE type_id = 34")
    conn.commit()
    conn.close()

    snapshot = api_client.get("/api/items/34").json()["latest_snapshot"]

    assert snapshot["buy_depth_5pct"] == 1200 and snapshot["sell_depth_5pct"] == 800
    assert snapshot["buy_gap_bp"] == 35 and snapshot["sell_gap_bp"] is None
    assert snapshot["buy_top_permille"] == 420


@pytest.mark.parametrize("price,limit_ok", [(95.0, True), (94.99, False)])
def test_the_depth_band_edge_is_inclusive(price, limit_ok):
    entry = build_orders_by_type([order(100.0, 1, True), order(price, 7, True)])[34]

    assert (entry["buy_depth_5pct"] == 8) is limit_ok
