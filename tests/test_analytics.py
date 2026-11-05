"""Métricas con consentimiento: ping/forget públicos, informe privado, retención y purga."""
import sqlite3
from datetime import datetime, timedelta, timezone

from backend.api import analytics
from tests.conftest import FAKE_CF_HEADER

VID = "a" * 8 + "-1111-2222-3333-" + "b" * 12
SID = "c" * 8 + "-4444-5555-6666-" + "d" * 12
OWN = {"Origin": "https://evemarket-analyzer.online"}


def _ping(http, **over):
    body = {"v": VID, "s": SID, "p": "/items/34-tritanium?x=1", "a": 0, "e": "view", "r": "", "l": "es"}
    body.update(over)
    return http.post("/api/analytics/ping", json=body, headers=OWN)


def _rows(db_path, sql):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_first_ping_creates_visitor_and_visit_without_the_query_string(client):
    http, db_path = client
    assert _ping(http, r="www.reddit.com").status_code == 204
    visitor = _rows(db_path, "SELECT * FROM analytics_visitor")[0]
    visit = _rows(db_path, "SELECT * FROM analytics_visit")[0]
    assert visitor["visitor_id"] == VID and visitor["visit_count"] == 1 and visitor["lang"] == "es"
    assert visit["landing_path"] == "/items/34-tritanium" and visit["ref_host"] == "www.reddit.com"


def test_own_site_referrer_is_not_stored(client):
    http, db_path = client
    _ping(http, r="evemarket-analyzer.online")
    assert _rows(db_path, "SELECT ref_host FROM analytics_visit")[0]["ref_host"] == ""


def test_followup_ping_updates_the_same_visit_and_caps_seconds_to_real_time(client):
    http, db_path = client
    _ping(http)
    _ping(http, e="ping", a=3600)  # claims an hour, but only a moment has passed
    _ping(http, e="view", a=0)
    visit = _rows(db_path, "SELECT * FROM analytics_visit")[0]
    assert len(_rows(db_path, "SELECT * FROM analytics_visit")) == 1
    assert visit["pageviews"] == 2
    assert 0 <= visit["active_seconds"] <= 10


def test_a_new_session_of_a_known_visitor_counts_as_a_return_visit(client):
    http, db_path = client
    _ping(http)
    _ping(http, s="e" * 8 + "-4444-5555-6666-" + "f" * 12)
    assert _rows(db_path, "SELECT visit_count FROM analytics_visitor")[0]["visit_count"] == 2


def test_invalid_ids_and_foreign_sessions_are_rejected(client):
    http, _ = client
    assert _ping(http, v="short").status_code == 400
    assert _ping(http, s="no válido con espacios y ñ ñ ñ ñ").status_code in (400, 422)
    _ping(http)
    other = "z" * 8 + "-1111-2222-3333-" + "y" * 12
    assert _ping(http, v=other).status_code == 400  # same session id, different visitor
    assert _ping(http, a=999999).status_code == 422


def test_cross_origin_ping_is_rejected(client):
    http, _ = client
    body = {"v": VID, "s": SID, "p": "/", "a": 0}
    assert http.post("/api/analytics/ping", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert http.post("/api/analytics/ping", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_forget_deletes_every_record_of_the_visitor(client):
    http, db_path = client
    _ping(http)
    assert http.post("/api/analytics/forget", json={"v": VID}, headers=OWN).status_code == 204
    assert _rows(db_path, "SELECT * FROM analytics_visitor") == []
    assert _rows(db_path, "SELECT * FROM analytics_visit") == []
    assert http.post("/api/analytics/forget", json={"v": "x"}, headers=OWN).status_code == 400


def test_summary_is_private(client):
    http, _ = client
    assert http.get("/api/private/analytics/summary").status_code == 401
    assert http.get("/api/private/analytics/summary?days=0", headers=FAKE_CF_HEADER).status_code == 400
    assert http.get("/api/private/analytics/summary", headers=FAKE_CF_HEADER).status_code == 200


def _seed(db_path, visitor, first_day, visit_days, seconds=60):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO analytics_visitor (visitor_id, first_seen, last_seen, visit_count) VALUES (?, ?, ?, ?)",
        (visitor, f"{first_day}T10:00:00+00:00", f"{visit_days[-1]}T10:00:00+00:00", len(visit_days)),
    )
    for n, day in enumerate(visit_days):
        conn.execute(
            "INSERT INTO analytics_visit (visit_id, visitor_id, started_at, last_ping_at, active_seconds, "
            "pageviews, landing_path, ref_host) VALUES (?, ?, ?, ?, ?, 2, '/', ?)",
            (f"{visitor}-{n}", visitor, f"{day}T10:00:00+00:00", f"{day}T10:01:00+00:00", seconds, "reddit.com"),
        )
    conn.commit()
    conn.close()


def test_summary_computes_retention_new_vs_returning_and_time(client):
    http, db_path = client
    today = datetime.now(timezone.utc).date()
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    _seed(db_path, "v-back-d1", d(10), [d(10), d(9)], seconds=120)   # came back on day 1
    _seed(db_path, "v-no-return", d(10), [d(10)], seconds=30)        # never came back
    _seed(db_path, "v-back-d7", d(8), [d(8), d(1)], seconds=60)      # came back on day 7
    _seed(db_path, "v-today", d(0), [d(0)], seconds=90)              # too recent for D1
    out = http.get("/api/private/analytics/summary?days=3", headers=FAKE_CF_HEADER).json()

    assert out["total_visitors"] == 4 and out["total_visits"] == 6
    assert out["returning_visitors"] == 2
    assert out["median_active_seconds"] == 75.0 and out["avg_active_seconds"] == 80.0
    assert out["top_referrers"] == [["reddit.com", 6]]
    by_day = {r["day"]: r for r in out["retention"]}
    assert (by_day[1]["eligible"], by_day[1]["returned"]) == (3, 1)   # v-today is not eligible yet
    assert (by_day[7]["eligible"], by_day[7]["returned"]) == (3, 1)
    assert by_day[30]["eligible"] == 0 and by_day[30]["rate"] == 0.0
    today_row = out["days"][-1]
    assert today_row["day"] == d(0) and today_row["visits"] == 1 and today_row["new_visitors"] == 1
    day_before = out["days"][-2]
    assert day_before["visits"] == 1 and day_before["returning_visitors"] == 1  # v-back-d7 on d(1)


def test_purge_removes_data_older_than_the_retention_window(client):
    http, db_path = client
    old = (datetime.now(timezone.utc) - timedelta(days=analytics.RETENTION_DAYS + 5)).date().isoformat()
    recent = datetime.now(timezone.utc).date().isoformat()
    _seed(db_path, "v-old", old, [old])
    _seed(db_path, "v-recent", recent, [recent])
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    analytics.purge_old(conn)
    conn.commit()
    assert [r["visitor_id"] for r in conn.execute("SELECT visitor_id FROM analytics_visitor")] == ["v-recent"]
    assert [r["visitor_id"] for r in conn.execute("SELECT visitor_id FROM analytics_visit")] == ["v-recent"]
    conn.close()


def test_pages_load_the_script_and_the_privacy_page_lists_every_language(client):
    http, db_path = client
    privacy = http.get("/privacy")
    assert privacy.status_code == 200
    for code in ("en", "es", "de", "fr", "it"):
        assert f'<section lang="{code}">' in privacy.text
    assert "data-eve-consent-settings" in privacy.text
    assert '<script src="/analytics.js" defer></script>' in privacy.text
    assert 'href="/privacy"' in http.get("/items").text
    import os
    script = open(os.path.join("frontend", "app", "public", "analytics.js"), encoding="utf-8").read()
    for key in ("eve_consent", "globalPrivacyControl", "/api/analytics/ping", "/api/analytics/forget"):
        assert key in script


def test_api_creates_the_analytics_tables_when_no_engine_has_run_init_db(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.main import app

    bare = tmp_path / "bare.db"
    sqlite3.connect(bare).close()  # an empty database: no tables at all
    monkeypatch.setenv("DB_PATH", str(bare))
    http = TestClient(app)
    assert _ping(http).status_code == 204
    assert http.get("/api/private/analytics/summary", headers=FAKE_CF_HEADER).json()["total_visits"] == 1
