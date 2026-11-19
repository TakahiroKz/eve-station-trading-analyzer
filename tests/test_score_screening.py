"""El ciclo de mercado guarda el puntaje junto al estado, sin cambiar el estado (analytics/scoring.py)."""
import json
import sqlite3

import pytest

from scheduler.run import _age_minutes, screen_opportunities
from storage.db import get_connection, init_db


@pytest.fixture
def screening_db(tmp_path):
    db_path = str(tmp_path / "score.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.execute(
        "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, sell_volume, "
        "buy_order_count, sell_order_count) VALUES (34, datetime('now'), 4.0, 6.0, 1000, 1000, 8, 9)",
    )
    for offset in range(7):
        conn.execute(
            "INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
            f"VALUES (34, date('now', '-{offset} day'), 4.2, 4.6, 3.9, 5000000, 400)",
        )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(autouse=True)
def no_external_side_effects(monkeypatch):
    monkeypatch.setattr("scheduler.run.get_current_wallet_balance", lambda: 5_000_000.0)
    monkeypatch.setattr("scheduler.run.dispatch", lambda events: None)


def test_screening_stores_the_score_and_the_inputs_needed_to_explain_it(tmp_path, screening_db):
    screen_opportunities(screening_db, str(tmp_path / "registro.xlsx"))

    conn = get_connection(screening_db)
    row = conn.execute("SELECT * FROM item_status WHERE type_id = 34").fetchone()
    conn.close()

    assert 0 <= row["score"] <= 100
    assert row["score_class"] in {"EXCELLENT", "HIGH", "MODERATE", "LOW", "DISCARDED"}
    assert row["eligibility"] in {"NO_ELIGIBLE", "ELIGIBLE", "RECOMMENDED"}
    assert row["recommendation"] in {"BUY_CANDIDATE", "WAIT", "REJECT"}
    assert row["score_version"].startswith("1.1.0-")
    inputs = json.loads(row["score_inputs"])
    assert set(inputs) == {"cv", "age", "sane", "bd", "sd"} and inputs["age"] is not None and inputs["age"] < 5
    # Precio medio constante en los 7 días: coeficiente de variación cero (hay >= 5 observaciones).
    assert inputs["cv"] == 0


def test_the_score_does_not_change_the_status(tmp_path, screening_db, monkeypatch):
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("EN_OBSERVACION", "borderline"))

    screen_opportunities(screening_db, str(tmp_path / "registro.xlsx"))

    conn = get_connection(screening_db)
    row = conn.execute("SELECT status, reason, score FROM item_status WHERE type_id = 34").fetchone()
    conn.close()
    assert row["status"] == "EN_OBSERVACION" and row["reason"] == "borderline" and row["score"] is not None


def test_a_discarded_status_caps_the_stored_score(tmp_path, screening_db, monkeypatch):
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("DESCARTADO", "no viable"))

    screen_opportunities(screening_db, str(tmp_path / "registro.xlsx"))

    conn = get_connection(screening_db)
    row = conn.execute("SELECT score, score_class, eligibility, recommendation FROM item_status").fetchone()
    conn.close()
    assert row["score"] <= 29 and row["score_class"] == "DISCARDED"
    assert row["eligibility"] == "NO_ELIGIBLE" and row["recommendation"] == "REJECT"


def test_migration_adds_the_score_columns_to_an_existing_database(tmp_path):
    db_path = str(tmp_path / "old.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(item_status)")}
    conn.close()
    assert {"score", "score_class", "eligibility", "recommendation", "score_version", "score_inputs"} <= columns

    init_db(db_path)  # idempotente: no falla con las columnas ya creadas


def test_age_minutes_handles_sqlite_timestamps_and_garbage():
    from datetime import datetime, timezone

    now = datetime(2026, 11, 19, 12, 10, tzinfo=timezone.utc)
    assert _age_minutes("2026-11-19 12:00:00", now) == 10
    assert _age_minutes("2026-11-19T11:55:00+00:00", now) == 15
    assert _age_minutes("2026-11-19T13:00:00+00:00", now) == 0  # el reloj nunca da edades negativas
    assert _age_minutes(None, now) is None and _age_minutes("ayer", now) is None
