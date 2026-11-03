"""Fixtures compartidas por los tests de la API (tests/test_api_main.py,
tests/test_api_private.py): un TestClient contra una DB temporal por test, y un
helper para sembrar un ítem clasificado con snapshot de mercado."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from storage.db import init_db

FAKE_CF_HEADER = {"Cf-Access-Jwt-Assertion": "header.payload.signature"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setattr("backend.api.private.get_current_wallet_balance", lambda: 1_234_567.0)
    return TestClient(app), db_path


def seed_item(
    db_path: str, type_id: int = 34, name: str = "Tritanium", status: str = "POTENCIAL",
    category_id: int | None = None, category_name: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (?, ?)", (type_id, name))
    conn.execute(
        "INSERT INTO item_status (type_id, status, reason, spread_bruto, evaluacion_spread, "
        "liquidez, roi, best_buy, best_sell, volumen_diario_real, last_evaluated_at) "
        "VALUES (?, ?, 'ok', 0.1, 'buena', 'alta', 0.2, 4.0, 4.5, 1000, datetime('now'))",
        (type_id, status),
    )
    conn.execute(
        "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) "
        "VALUES (?, datetime('now'), 4.0, 4.5, 1000, 1000, 3, 3)",
        (type_id,),
    )
    if category_id is not None:
        conn.execute(
            "INSERT INTO item_category (type_id, group_id, group_name, category_id, category_name) "
            "VALUES (?, 1, 'Grupo', ?, ?)",
            (type_id, category_id, category_name),
        )
    conn.commit()
    conn.close()
