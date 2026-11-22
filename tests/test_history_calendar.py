"""Calendario del histórico de la ESI: qué día debe estar publicado y cuándo se considera retraso real."""
import sqlite3
from datetime import datetime, timezone

import pytest

from analytics import history_calendar
from analytics.history_calendar import expected_date, history_info
from backend.api import main as api_main
from tests.conftest import seed_item


def at(day: str, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=timezone.utc)


def test_expected_date_flips_at_the_publication_margin():
    assert expected_date(at("2026-11-22", 6)).isoformat() == "2026-11-20"       # la ESI aún no publica el 21
    assert expected_date(at("2026-11-22", 11, 14)).isoformat() == "2026-11-20"
    assert expected_date(at("2026-11-22", 11, 15)).isoformat() == "2026-11-21"
    assert expected_date(at("2026-11-22", 23, 59)).isoformat() == "2026-11-21"


def test_before_publication_the_previous_day_is_not_late_and_says_when_the_next_one_arrives():
    info = history_info("2026-11-20", at("2026-11-22", 6))
    assert info["late"] is False
    assert info["latest_date"] == "2026-11-20" and info["next_date"] == "2026-11-21"
    assert info["next_publish_at"] == "2026-11-22T11:05:00Z"


def test_after_publication_a_missing_day_is_late():
    assert history_info("2026-11-20", at("2026-11-22", 11, 15))["late"] is True
    assert history_info("2026-11-20", at("2026-11-22", 18))["late"] is True
    assert history_info("2026-11-21", at("2026-11-22", 18))["late"] is False


def test_next_publication_after_a_current_day_is_tomorrow():
    info = history_info("2026-11-21", at("2026-11-22", 18))
    assert info["next_date"] == "2026-11-22" and info["next_publish_at"] == "2026-11-23T11:05:00Z"


def test_no_data_or_garbage_counts_as_late_and_never_raises():
    assert history_info(None, at("2026-11-22", 6))["late"] is True
    info = history_info("no-es-fecha", at("2026-11-22", 6))
    assert info["late"] is True and info["latest_date"] is None


def test_the_scheduler_uses_the_same_calendar():
    from scheduler import run
    assert run.history_expected_date is history_calendar.expected_date


@pytest.fixture
def detail(client, monkeypatch):
    api_client, db_path = client
    seed_item(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
                 "VALUES (34, '2026-11-20', 4.2, 4.6, 3.9, 1000, 5)")
    conn.commit()
    conn.close()
    api_main._HISTORY_LATEST.clear()
    return api_client, monkeypatch


def test_item_detail_reports_the_history_state(detail):
    api_client, monkeypatch = detail
    monkeypatch.setattr(api_main, "history_info", lambda latest: history_info(latest, at("2026-11-22", 6)))
    info = api_client.get("/api/items/34").json()["history_info"]
    assert info["latest_date"] == "2026-11-20" and info["late"] is False and info["next_publish_at"] == "2026-11-22T11:05:00Z"


def test_item_detail_flags_a_real_delay(detail):
    api_client, monkeypatch = detail
    monkeypatch.setattr(api_main, "history_info", lambda latest: history_info(latest, at("2026-11-22", 15)))
    assert api_client.get("/api/items/34").json()["history_info"]["late"] is True


def test_the_market_latest_date_is_cached_for_ten_minutes(detail):
    api_client, _ = detail
    first = api_client.get("/api/items/34").json()["history_info"]["latest_date"]
    assert first == "2026-11-20"
    conn = sqlite3.connect(api_main.os.environ["DB_PATH"])
    conn.execute("INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
                 "VALUES (34, '2026-11-21', 4.2, 4.6, 3.9, 1000, 5)")
    conn.commit()
    conn.close()
    assert api_client.get("/api/items/34").json()["history_info"]["latest_date"] == "2026-11-20"   # aún en caché
    api_main._HISTORY_LATEST.clear()
    assert api_client.get("/api/items/34").json()["history_info"]["latest_date"] == "2026-11-21"
