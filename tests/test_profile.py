"""Perfil y capital del jugador (fase 3 de EF-02): perfil efectivo, lectura de ESI, sincronización y rutas /api/me/*."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import auth as auth_module
from backend.api.main import app
from finance.fees import Profile
from finance.hubs import HUB_BY_MARKET, HUBS
from finance.user_profile import build_profile, fee_summary, resolve_skills, resolve_standings
from ingestion import esi_profile
from ingestion.eve_login import REQUIRED_SCOPES
from storage import token_crypto, users_db

KEY = token_crypto.generate_key()
REFRESH = "refresh-SECRET"
CID = 93000001
NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
JITA = HUB_BY_MARKET["jita"]


# ---- Perfil efectivo (puro) ----------------------------------------------------------------------------------------

def test_no_data_means_the_default_profile_that_reproduces_the_historic_constants():
    profile, skills, standings = build_profile(JITA, None, None, None)
    assert profile == Profile(source="MANUAL")
    assert {v["source"] for v in (*skills.values(), *standings.values())} == {"DEFAULT"}
    assert fee_summary(profile) == {"broker_fee_pct": 2.4, "sales_tax_pct": 7.5}      # 0,901 / 1,024 de siempre


def test_esi_skills_and_standings_drive_the_fees():
    esi_skills = {"broker_relations": 5, "advanced_broker_relations": 3, "accounting": 5}
    esi_standings = {"faction": {"500001": "5"}, "corp": {"1000035": "5"}}
    profile, skills, standings = build_profile(JITA, esi_skills, esi_standings, None)
    assert profile.source == "ESI" and skills["accounting"]["source"] == "ESI"
    assert fee_summary(profile) == {"broker_fee_pct": 1.25, "sales_tax_pct": 3.375}   # 3 − 1,5 − 0,15 − 0,10 ; 7,5·(1−0,55)


def test_manual_beats_esi_and_marks_the_profile_as_manual():
    esi = {"broker_relations": 5, "advanced_broker_relations": 0, "accounting": 5}
    profile, skills, _ = build_profile(JITA, esi, {"faction": {"500001": "0"}, "corp": {"1000035": "0"}},
                                       {"skills": {"accounting": 2}})
    assert skills["accounting"] == {"value": 2, "source": "MANUAL", "esi": 5}
    assert skills["broker_relations"]["source"] == "ESI" and profile.source == "MANUAL"


def test_standing_absent_from_esi_is_zero_only_if_esi_was_read():
    never = resolve_standings(JITA, None, None)
    assert never["corp"] == {"value": Decimal(0), "source": "DEFAULT", "esi": None}
    read = resolve_standings(JITA, {"faction": {"500001": "0"}, "corp": {"1000035": "0"}}, None)
    assert read["corp"]["source"] == "ESI" and read["corp"]["value"] == 0


@pytest.mark.parametrize("bad", [6, -1, True, "3", 2.5, None])
def test_corrupt_stored_skill_levels_fall_back_instead_of_breaking(bad):
    out = resolve_skills({"accounting": bad}, {"accounting": bad})
    assert out["accounting"]["source"] == "DEFAULT" and out["accounting"]["value"] == 0


@pytest.mark.parametrize("bad", ["abc", "11", "-11", "nan", "inf"])
def test_corrupt_stored_standings_fall_back(bad):
    out = resolve_standings(JITA, {"faction": {"500001": bad}, "corp": {"1000035": bad}}, {"faction": bad, "corp": bad})
    assert out["faction"]["source"] == "DEFAULT" and out["corp"]["source"] == "DEFAULT"


def test_each_market_uses_its_own_station_owner_and_faction():
    assert {h.market_id for h in HUBS} == {"jita", "amarr", "dodixie", "rens", "hek"}
    assert len({h.station_id for h in HUBS}) == 5 and len({h.owner_corp_id for h in HUBS}) == 5
    esi = {"faction": {"500002": "4"}, "corp": {"1000049": "2", "1000057": "0"}}
    rens, hek = HUB_BY_MARKET["rens"], HUB_BY_MARKET["hek"]
    assert resolve_standings(rens, esi, None)["corp"]["value"] == 2 and resolve_standings(hek, esi, None)["corp"]["value"] == 0
    assert resolve_standings(rens, esi, None)["faction"]["value"] == resolve_standings(hek, esi, None)["faction"]["value"] == 4


# ---- Lectura de ESI ------------------------------------------------------------------------------------------------

def fake_get(responses):
    def _get(path, token):
        value = responses[path.split("/characters/")[1].split("/", 1)[1].strip("/")]
        if isinstance(value, Exception):
            raise value
        return value
    return _get


def test_fetch_skills_reads_only_the_three_trade_skills_and_defaults_to_zero(monkeypatch):
    payload = {"skills": [{"skill_id": 3446, "active_skill_level": 4, "trained_skill_level": 5},
                          {"skill_id": 16622, "active_skill_level": 3}, {"skill_id": 999, "active_skill_level": 5}]}
    monkeypatch.setattr(esi_profile, "_get", fake_get({"skills": payload}))
    assert esi_profile.fetch_skills("t", 1) == {"broker_relations": 4, "advanced_broker_relations": 0, "accounting": 3}


def test_fetch_standings_keeps_only_reference_factions_and_corps(monkeypatch):
    payload = [{"from_id": 500001, "from_type": "faction", "standing": 2.5},
               {"from_id": 1000035, "from_type": "npc_corp", "standing": -1.25},
               {"from_id": 1000035, "from_type": "agent", "standing": 9},      # un agente con el mismo id: se ignora
               {"from_id": 3004, "from_type": "agent", "standing": 5},
               {"from_id": 500003, "from_type": "faction", "standing": 12},    # fuera de rango: se descarta
               {"from_id": 500004, "from_type": "faction", "standing": "x"}]
    monkeypatch.setattr(esi_profile, "_get", fake_get({"standings": payload}))
    out = esi_profile.fetch_standings("t", 1)
    assert out["faction"]["500001"] == "2.5" and out["corp"]["1000035"] == "-1.25"
    assert out["faction"]["500003"] == "0" and out["faction"]["500004"] == "0" and out["corp"]["1000086"] == "0"
    assert set(out["faction"]) == {"500001", "500002", "500003", "500004"} and len(out["corp"]) == 5


def test_fetch_wallet_formats_and_rejects_garbage(monkeypatch):
    monkeypatch.setattr(esi_profile, "_get", fake_get({"wallet": 1234567.891}))
    assert esi_profile.fetch_wallet("t", 1) == "1234567.89"
    for bad in (True, "12", None, -5, [1]):
        monkeypatch.setattr(esi_profile, "_get", fake_get({"wallet": bad}))
        with pytest.raises(esi_profile.EsiProfileError):
            esi_profile.fetch_wallet("t", 1)


@pytest.mark.parametrize("status,kind", [(401, "REVOKED"), (403, "SCOPE"), (500, "UNAVAILABLE"), (420, "UNAVAILABLE")])
def test_esi_http_errors_map_to_states(monkeypatch, status, kind):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(status, request=httpx.Request("GET", "http://x")))
    with pytest.raises(esi_profile.EsiProfileError) as exc:
        esi_profile._get("/characters/1/skills/", "t")
    assert exc.value.kind == kind


def test_network_failure_and_bad_json_are_unavailable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    with pytest.raises(esi_profile.EsiProfileError) as exc:
        esi_profile._get("/x", "t")
    assert exc.value.kind == "UNAVAILABLE"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, content=b"<html>", request=httpx.Request("GET", "http://x")))
    with pytest.raises(esi_profile.EsiProfileError):
        esi_profile._get("/x", "t")


def test_invalid_grant_means_revoked_but_other_errors_do_not(monkeypatch):
    def failing(code, body):
        def _refresh(*a, **k):
            raise httpx.HTTPStatusError("x", request=httpx.Request("POST", "http://x"),
                                        response=httpx.Response(code, json=body, request=httpx.Request("POST", "http://x")))
        return _refresh
    monkeypatch.setattr(esi_profile.esi_auth, "refresh_access_token", failing(400, {"error": "invalid_grant"}))
    with pytest.raises(esi_profile.EsiProfileError) as exc:
        esi_profile.refresh_access("c", "s", "r")
    assert exc.value.kind == "REVOKED"
    monkeypatch.setattr(esi_profile.esi_auth, "refresh_access_token", failing(400, {"error": "invalid_client"}))
    with pytest.raises(esi_profile.EsiProfileError) as exc:
        esi_profile.refresh_access("c", "s", "r")
    assert exc.value.kind == "UNAVAILABLE"
    monkeypatch.setattr(esi_profile.esi_auth, "refresh_access_token", failing(503, {}))
    with pytest.raises(esi_profile.EsiProfileError) as exc:
        esi_profile.refresh_access("c", "s", "r")
    assert exc.value.kind == "UNAVAILABLE"


# ---- Sincronización ------------------------------------------------------------------------------------------------

class Esi:
    """ESI de mentira: cuenta las llamadas y permite fallar o rotar el refresh token."""
    def __init__(self):
        self.calls = []
        self.fail: dict[str, str] = {}
        self.rotate_to: str | None = None
        self.wallet = 5_000_000.5
        self.skills = {"skills": [{"skill_id": 3446, "active_skill_level": 5}, {"skill_id": 16622, "active_skill_level": 4}]}
        self.standings = [{"from_id": 500001, "from_type": "faction", "standing": 3.0}]

    def refresh(self, client_id, secret, refresh_token):
        self.calls.append("refresh")
        if "refresh" in self.fail:
            raise esi_profile.EsiProfileError(self.fail["refresh"])
        out = {"access_token": "AT"}
        if self.rotate_to:
            out["refresh_token"] = self.rotate_to
        return out

    def get(self, path, token):
        what = path.split("/")[3]
        self.calls.append(what)
        if what in self.fail:
            raise esi_profile.EsiProfileError(self.fail[what])
        return {"skills": self.skills, "standings": self.standings, "wallet": self.wallet}[what]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("USERS_ENC_KEYS", KEY)
    path = str(tmp_path / "users.db")
    users_db.init_users_db(path)
    conn = users_db.connect(path)
    users_db.upsert_user(conn, CID, "Pilot", "2026-11-19", NOW)
    users_db.save_token(conn, CID, token_crypto.encrypt(REFRESH, CID), " ".join(REQUIRED_SCOPES), NOW)
    conn.commit()
    esi = Esi()
    monkeypatch.setattr(esi_profile, "refresh_access", esi.refresh)
    monkeypatch.setattr(esi_profile, "_get", esi.get)
    yield conn, esi
    conn.close()


def sync(conn, now=NOW, **kw):
    return esi_profile.sync_profile(conn, CID, "cid", "secret", now, **kw)


def test_first_sync_stores_skills_and_standings_but_not_the_wallet(world):
    conn, esi = world
    assert sync(conn) == "OK"
    p = users_db.get_profile(conn, CID)
    assert json.loads(p["skills_json"]) == {"accounting": 4, "advanced_broker_relations": 0, "broker_relations": 5}
    assert json.loads(p["standings_json"])["faction"]["500001"] == "3"
    assert p["skills_at"] == "2026-11-20T12:00:00Z" and p["wallet_isk"] is None and p["sync_status"] == "OK"
    assert esi.calls == ["refresh", "skills", "standings"]


def test_second_call_is_free_until_a_day_has_passed(world):
    conn, esi = world
    sync(conn)
    esi.calls.clear()
    assert sync(conn, NOW + timedelta(hours=23, minutes=59)) == "NOT_NEEDED" and esi.calls == []
    assert sync(conn, NOW + timedelta(hours=24)) == "OK" and esi.calls == ["refresh", "skills", "standings"]


def test_attempts_are_throttled_even_when_forced(world):
    conn, esi = world
    sync(conn)
    esi.calls.clear()
    assert sync(conn, NOW + timedelta(minutes=4, seconds=59), force=True) == "THROTTLED" and esi.calls == []
    assert sync(conn, NOW + timedelta(minutes=5), force=True) == "OK" and esi.calls


def test_failed_attempts_are_throttled_too_and_keep_the_old_data(world):
    conn, esi = world
    sync(conn)
    esi.fail["skills"] = "UNAVAILABLE"
    later = NOW + timedelta(hours=25)
    assert sync(conn, later) == "UNAVAILABLE"
    assert json.loads(users_db.get_profile(conn, CID)["skills_json"])["broker_relations"] == 5   # no se pierde lo anterior
    esi.calls.clear()
    assert sync(conn, later + timedelta(minutes=1)) == "THROTTLED" and esi.calls == []


def test_wallet_is_read_on_demand_and_cached_five_minutes(world):
    conn, esi = world
    sync(conn)
    esi.calls.clear()
    assert sync(conn, NOW + timedelta(minutes=5), want_wallet=True) == "OK"
    assert esi.calls == ["refresh", "wallet"]                     # no vuelve a pedir habilidades
    assert users_db.get_profile(conn, CID)["wallet_isk"] == "5000000.50"
    esi.calls.clear()
    assert sync(conn, NOW + timedelta(minutes=9), want_wallet=True) == "NOT_NEEDED" and esi.calls == []
    esi.wallet = 7.0
    assert sync(conn, NOW + timedelta(minutes=10, seconds=1), want_wallet=True) == "OK"
    assert users_db.get_profile(conn, CID)["wallet_isk"] == "7.00"


def test_revoked_token_is_marked_and_no_more_calls_are_made(world):
    conn, esi = world
    esi.fail["refresh"] = "REVOKED"
    assert sync(conn) == "REVOKED"
    assert users_db.get_token(conn, CID)["status"] == "REVOKED"
    esi.calls.clear()
    assert sync(conn, NOW + timedelta(hours=1), force=True) == "REVOKED" and esi.calls == []


def test_a_missing_permission_gives_partial_and_skips_that_call(world):
    conn, esi = world
    conn.execute("UPDATE user_token SET scopes = ?", (REQUIRED_SCOPES[0],))
    conn.commit()
    assert sync(conn, want_wallet=True) == "PARTIAL"
    assert esi.calls == ["refresh", "skills"]
    p = users_db.get_profile(conn, CID)
    assert p["skills_json"] and p["standings_json"] is None and p["wallet_isk"] is None


def test_esi_403_is_partial_not_a_crash(world):
    conn, esi = world
    esi.fail["standings"] = "SCOPE"
    assert sync(conn) == "PARTIAL"


def test_rotated_refresh_token_is_saved_encrypted(world):
    conn, esi = world
    esi.rotate_to = "NEW-refresh-SECRET"
    sync(conn)
    blob = bytes(users_db.get_token(conn, CID)["refresh_token_enc"])
    assert b"NEW-refresh" not in blob and token_crypto.decrypt(blob, CID) == "NEW-refresh-SECRET"
    assert users_db.get_token(conn, CID)["scopes"] == " ".join(REQUIRED_SCOPES)


def test_unreadable_token_is_unavailable_not_an_exception(world, monkeypatch):
    conn, _ = world
    monkeypatch.setenv("USERS_ENC_KEYS", token_crypto.generate_key())      # la clave del token ya no está
    assert sync(conn) == "UNAVAILABLE"


def test_no_token_is_revoked(world):
    conn, _ = world
    users_db.delete_token(conn, CID)
    assert sync(conn) == "REVOKED"


def test_staleness_after_48_hours_without_a_successful_read(world):
    conn, esi = world
    sync(conn)
    p = users_db.get_profile(conn, CID)
    assert not esi_profile.is_stale(p, NOW + timedelta(hours=47)) and esi_profile.is_stale(p, NOW + timedelta(hours=48))
    assert not esi_profile.is_stale(None, NOW)


# ---- Rutas ---------------------------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("USERS_ENC_KEYS", KEY)
    monkeypatch.setenv("EVE_LOGIN_CLIENT_ID", "cid")
    monkeypatch.setenv("EVE_LOGIN_CLIENT_SECRET", "secret")
    users_db.init_users_db()
    esi = Esi()
    monkeypatch.setattr(esi_profile, "refresh_access", esi.refresh)
    monkeypatch.setattr(esi_profile, "_get", esi.get)
    monkeypatch.setattr(auth_module.esi_auth, "exchange_code_for_token",
                        lambda c, s, code: {"access_token": "AT", "refresh_token": REFRESH})
    monkeypatch.setattr(auth_module, "verify_access_token", lambda t, c: (CID, "Pilot One", list(REQUIRED_SCOPES)))
    client = TestClient(app, follow_redirects=False)
    from urllib.parse import parse_qs, urlparse
    first = client.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}")
    state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
    client.get(f"/api/auth/callback?code=abc&state={state}")
    client.esi = esi
    return client


def test_routes_need_a_session_and_the_feature_on(tmp_path, monkeypatch):
    for name in ("EVE_LOGIN_CLIENT_ID", "EVE_LOGIN_CLIENT_SECRET", "USERS_ENC_KEYS"):
        monkeypatch.delenv(name, raising=False)
    c = TestClient(app, follow_redirects=False)
    for method, path in (("get", "/api/me/profile"), ("get", "/api/me/capital"), ("post", "/api/me/profile/refresh"),
                         ("put", "/api/me/profile/override")):
        assert getattr(c, method)(path).status_code in (503, 422), path
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "u.db"))
    monkeypatch.setenv("USERS_ENC_KEYS", KEY)
    monkeypatch.setenv("EVE_LOGIN_CLIENT_ID", "cid")
    monkeypatch.setenv("EVE_LOGIN_CLIENT_SECRET", "secret")
    users_db.init_users_db()
    for path in ("/api/me/profile", "/api/me/capital"):
        r = c.get(path)
        assert r.status_code == 401 and r.headers["cache-control"] == "no-store"
    assert c.post("/api/me/profile/refresh").status_code == 401
    assert c.put("/api/me/profile/override", json={}).status_code == 401


def test_profile_reads_esi_on_first_visit_and_shows_the_source_of_each_value(api):
    r = api.get("/api/me/profile")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["character"] == {"id": CID, "name": "Pilot One"} and body["sync"]["status"] == "OK"
    assert body["skills"]["broker_relations"] == {"value": 5, "source": "ESI", "esi": 5}
    jita = next(m for m in body["markets"] if m["market_id"] == "jita")
    assert jita["standings"]["faction"] == {"value": 3.0, "source": "ESI", "esi": 3.0}
    assert jita["fees"] == {"broker_fee_pct": 1.41, "sales_tax_pct": 4.2, "source": "ESI"}   # 3−1,5−0,09 ; 7,5·(1−0,44)
    assert len(body["markets"]) == 5 and body["sync"]["missing_scopes"] == [] and not body["sync"]["stale"]
    assert api.esi.calls == ["refresh", "skills", "standings"]
    api.get("/api/me/profile")
    assert api.esi.calls == ["refresh", "skills", "standings"], "la segunda visita no vuelve a ESI"


def test_no_secret_ever_appears_in_responses(api):
    texts = [api.get("/api/me/profile").text, api.get("/api/me/capital").text, api.get("/api/auth/me/export").text]
    for text in texts:
        assert REFRESH not in text and "AT" != text and "refresh_token_enc" not in text


def test_override_is_validated_applied_and_clearable(api):
    api.get("/api/me/profile")                                   # primera lectura de ESI
    ok = api.put("/api/me/profile/override", json={"skills": {"accounting": 5}, "standings": {"jita": {"corp": 10}}})
    assert ok.status_code == 200
    body = ok.json()
    assert body["skills"]["accounting"] == {"value": 5, "source": "MANUAL", "esi": 4} and body["has_override"] is True
    jita = next(m for m in body["markets"] if m["market_id"] == "jita")
    assert jita["standings"]["corp"]["source"] == "MANUAL" and jita["fees"]["source"] == "MANUAL"
    cleared = api.put("/api/me/profile/override", json={})
    assert cleared.json()["has_override"] is False and cleared.json()["skills"]["accounting"]["source"] == "ESI"


@pytest.mark.parametrize("body", [
    {"skills": {"accounting": 6}}, {"skills": {"accounting": -1}}, {"skills": {"accounting": 2.5}},
    {"skills": {"accounting": "x"}}, {"skills": {"unknown": 1}}, {"extra": 1},
    {"standings": {"jita": {"corp": 11}}}, {"standings": {"jita": {"faction": -10.5}}},
    {"standings": {"nowhere": {"corp": 1}}}, {"standings": {"jita": {"corp": "nan"}}},
    {"standings": {"jita": {"corp": 1, "other": 2}}},
])
def test_override_rejects_invalid_input(api, body):
    assert api.put("/api/me/profile/override", json=body).status_code == 422
    assert api.get("/api/me/profile").json()["has_override"] is False


def test_manual_refresh_is_throttled_with_retry_after(api):
    api.get("/api/me/profile")
    r = api.post("/api/me/profile/refresh")
    assert r.status_code == 429 and r.headers["retry-after"] == "300"


def test_manual_refresh_works_after_the_gap(api, monkeypatch):
    api.get("/api/me/profile")
    conn = users_db.connect()
    old = users_db.iso(datetime.now(timezone.utc) - timedelta(minutes=6))
    conn.execute("UPDATE user_profile SET last_attempt_at = ?", (old,))
    conn.commit()
    conn.close()
    api.esi.calls.clear()
    assert api.post("/api/me/profile/refresh").status_code == 200 and "skills" in api.esi.calls


def test_unsafe_methods_check_the_origin(api):
    evil = {"Origin": "https://evil.example"}
    assert api.put("/api/me/profile/override", json={}, headers=evil).status_code == 403
    assert api.post("/api/me/profile/refresh", headers=evil).status_code == 403


def test_capital_returns_the_wallet_and_caches_it(api):
    r = api.get("/api/me/capital")
    assert r.status_code == 200 and r.json()["wallet_isk"] == "5000000.50" and r.json()["sync"]["status"] == "OK"
    api.esi.calls.clear()
    api.get("/api/me/capital")
    assert "wallet" not in api.esi.calls


def test_revoked_access_is_reported_to_the_user(api):
    api.esi.fail["refresh"] = "REVOKED"
    conn = users_db.connect()
    conn.execute("UPDATE user_profile SET skills_at = NULL")
    conn.commit()
    conn.close()
    body = api.get("/api/me/profile").json()
    assert body["sync"]["status"] == "REVOKED"
    assert body["markets"][0]["fees"]["source"] == "MANUAL" and body["skills"]["accounting"]["source"] in ("ESI", "DEFAULT")


def test_missing_scopes_are_listed(api):
    conn = users_db.connect()
    conn.execute("UPDATE user_token SET scopes = ?", (REQUIRED_SCOPES[0],))
    conn.commit()
    conn.close()
    assert api.get("/api/me/profile").json()["sync"]["missing_scopes"] == sorted(REQUIRED_SCOPES[1:])


def test_old_consent_blocks_the_profile(api):
    conn = users_db.connect()
    conn.execute("UPDATE user SET consent_version = 'old'")
    conn.commit()
    conn.close()
    assert api.get("/api/me/profile").status_code == 403


def test_export_includes_the_profile_and_delete_removes_it(api):
    api.get("/api/me/capital")
    data = api.get("/api/auth/me/export").json()
    assert data["profile"]["wallet_isk"] == "5000000.50" and "refresh_token_enc" not in json.dumps(data)
    assert api.delete("/api/auth/me").status_code == 200
    conn = users_db.connect()
    assert conn.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0] == 0
    conn.close()
