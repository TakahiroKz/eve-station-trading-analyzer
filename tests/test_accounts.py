"""Cuentas EVE (fase 2 de EF-02): cifrado de tokens, users.db, verificación del JWT de CCP y rutas /api/auth/*."""
import json
import logging
import os
import sqlite3
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from backend.api import auth as auth_module
from backend.api.main import app
from ingestion.eve_login import REQUIRED_SCOPES, LoginError, verify_access_token
from storage import token_crypto, users_db

KEY_A, KEY_B = token_crypto.generate_key(), token_crypto.generate_key()
REFRESH = "refresh-token-SECRET-value"
CLIENT_ID = "test-client-id"


# ---- Cifrado -------------------------------------------------------------------------------------------------------

def test_encrypt_round_trip_and_ciphertext_hides_the_token():
    blob = token_crypto.encrypt(REFRESH, 42, KEY_A)
    assert REFRESH.encode() not in blob
    assert token_crypto.decrypt(blob, 42, KEY_A) == REFRESH
    assert token_crypto.encrypt(REFRESH, 42, KEY_A) != blob, "el nonce es aleatorio"


def test_blob_is_bound_to_the_character_and_to_the_key():
    blob = token_crypto.encrypt(REFRESH, 42, KEY_A)
    with pytest.raises(token_crypto.CryptoError):
        token_crypto.decrypt(blob, 43, KEY_A)                       # copiado a otra fila
    with pytest.raises(token_crypto.CryptoError):
        token_crypto.decrypt(blob, 42, KEY_B)                       # clave que ya no está
    tampered = bytearray(blob)
    tampered[-1] ^= 1
    with pytest.raises(token_crypto.CryptoError):
        token_crypto.decrypt(bytes(tampered), 42, KEY_A)
    with pytest.raises(token_crypto.CryptoError):
        token_crypto.decrypt(b"\x02" + blob[1:], 42, KEY_A)
    with pytest.raises(token_crypto.CryptoError):
        token_crypto.decrypt(b"short", 42, KEY_A)


def test_key_rotation_keeps_old_blobs_readable_and_flags_them():
    old = token_crypto.encrypt(REFRESH, 7, KEY_A)
    both = f"{KEY_B},{KEY_A}"
    assert token_crypto.decrypt(old, 7, both) == REFRESH
    assert token_crypto.needs_rotation(old, both) is True
    new = token_crypto.encrypt(REFRESH, 7, both)
    assert token_crypto.needs_rotation(new, both) is False
    assert token_crypto.decrypt(new, 7, both) == REFRESH


@pytest.mark.parametrize("raw", ["", "   ", "not base64 !!", "QUJD"])
def test_bad_key_configuration_fails_closed(raw):
    with pytest.raises(token_crypto.CryptoError):
        token_crypto.encrypt(REFRESH, 1, raw)


# ---- users.db ------------------------------------------------------------------------------------------------------

@pytest.fixture
def udb(tmp_path):
    path = str(tmp_path / "users.db")
    users_db.init_users_db(path)
    conn = users_db.connect(path)
    yield conn
    conn.close()


def test_schema_and_file_permissions(tmp_path):
    path = str(tmp_path / "u.db")
    users_db.init_users_db(path)
    users_db.init_users_db(path)                                        # idempotente
    conn = users_db.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"user", "user_token", "user_session"} <= tables
    assert conn.execute("PRAGMA user_version").fetchone()[0] == users_db.SCHEMA_VERSION
    conn.close()
    if os.name == "posix":
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_upsert_keeps_creation_date_and_updates_name(udb):
    t0 = users_db.utcnow()
    users_db.upsert_user(udb, 1, "Old", "v1", t0)
    users_db.upsert_user(udb, 1, "New", "v2", t0 + timedelta(days=1))
    row = udb.execute("SELECT * FROM user WHERE character_id = 1").fetchone()
    assert row["name"] == "New" and row["consent_version"] == "v2"
    assert row["created_at"] == users_db.iso(t0) and row["last_seen_at"] == users_db.iso(t0 + timedelta(days=1))


def test_session_stores_only_a_hash_and_expires(udb):
    now = users_db.utcnow()
    users_db.upsert_user(udb, 1, "A", "v", now)
    raw = users_db.create_session(udb, 1, now)
    stored = udb.execute("SELECT token_hash FROM user_session").fetchone()[0]
    assert stored != raw and raw not in stored and len(stored) == 64
    assert users_db.get_session_user(udb, raw, now)["character_id"] == 1
    assert users_db.get_session_user(udb, raw + "x", now) is None
    assert users_db.get_session_user(udb, None, now) is None
    assert users_db.get_session_user(udb, "a" * 500, now) is None
    assert users_db.get_session_user(udb, raw, now + timedelta(days=users_db.SESSION_TTL_DAYS, seconds=1)) is None


def test_session_slides_at_most_once_an_hour(udb):
    now = users_db.utcnow()
    users_db.upsert_user(udb, 1, "A", "v", now)
    raw = users_db.create_session(udb, 1, now)
    before = udb.execute("SELECT expires_at FROM user_session").fetchone()[0]
    users_db.get_session_user(udb, raw, now + timedelta(minutes=10))
    assert udb.execute("SELECT expires_at FROM user_session").fetchone()[0] == before
    users_db.get_session_user(udb, raw, now + timedelta(hours=2))
    assert udb.execute("SELECT expires_at FROM user_session").fetchone()[0] > before


def test_delete_user_cascades_and_other_users_survive(udb):
    now = users_db.utcnow()
    for cid in (1, 2):
        users_db.upsert_user(udb, cid, f"U{cid}", "v", now)
        users_db.save_token(udb, cid, b"x" * 40, "scope", now)
        users_db.create_session(udb, cid, now)
    users_db.delete_user(udb, 1)
    assert [r[0] for r in udb.execute("SELECT character_id FROM user")] == [2]
    assert udb.execute("SELECT COUNT(*) FROM user_token WHERE character_id = 1").fetchone()[0] == 0
    assert udb.execute("SELECT COUNT(*) FROM user_session WHERE character_id = 1").fetchone()[0] == 0
    assert udb.execute("SELECT COUNT(*) FROM user_token WHERE character_id = 2").fetchone()[0] == 1


def test_purge_inactive_and_expired(udb):
    now = users_db.utcnow()
    users_db.upsert_user(udb, 1, "Old", "v", now - timedelta(days=400))
    users_db.upsert_user(udb, 2, "Recent", "v", now - timedelta(days=100))
    users_db.create_session(udb, 2, now - timedelta(days=60))             # caducada (30 días)
    assert users_db.purge_expired_sessions(udb, now) == 1
    assert users_db.purge_inactive_users(udb, now) == 1
    assert [r[0] for r in udb.execute("SELECT character_id FROM user")] == [2]


def test_export_never_includes_the_token(udb):
    now = users_db.utcnow()
    users_db.upsert_user(udb, 1, "A", "v", now)
    users_db.save_token(udb, 1, token_crypto.encrypt(REFRESH, 1, KEY_A), "s1 s2", now)
    data = users_db.export_user(udb, 1)
    assert data["token"] == {"scopes": "s1 s2", "status": "ACTIVE", "updated_at": users_db.iso(now)}
    assert "refresh_token_enc" not in json.dumps(data) and users_db.export_user(udb, 99) is None


# ---- Verificación del JWT de CCP -----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def signing():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid="kid-1", alg="RS256", use="sig")
    return private, {"keys": [jwk]}


def make_token(private, **over):
    claims = {"iss": "https://login.eveonline.com", "aud": [CLIENT_ID, "EVE Online"],
              "sub": "CHARACTER:EVE:93000001", "name": "Pilot One", "exp": int(time.time()) + 600,
              "scp": list(REQUIRED_SCOPES)}
    kid = over.pop("_kid", "kid-1")
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


def test_valid_token_yields_character_name_and_scopes(signing):
    private, jwks = signing
    assert verify_access_token(make_token(private), CLIENT_ID, jwks) == (93000001, "Pilot One", list(REQUIRED_SCOPES))
    legacy_iss = make_token(private, iss="login.eveonline.com", scp="one-scope")
    assert verify_access_token(legacy_iss, CLIENT_ID, jwks)[2] == ["one-scope"]


@pytest.mark.parametrize("over", [
    {"aud": ["other-client", "EVE Online"]}, {"exp": int(time.time()) - 5}, {"iss": "https://evil.example"},
    {"sub": "CHARACTER:EVE:abc"}, {"sub": "USER:EVE:1"}, {"sub": None}, {"exp": None},
])
def test_invalid_claims_are_rejected(signing, over):
    private, jwks = signing
    with pytest.raises(LoginError):
        verify_access_token(make_token(private, **over), CLIENT_ID, jwks)


def test_wrong_signature_unknown_kid_and_wrong_algorithm_are_rejected(signing):
    private, jwks = signing
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(LoginError):
        verify_access_token(make_token(other), CLIENT_ID, jwks)
    with pytest.raises(LoginError):
        verify_access_token(make_token(private, _kid="nope"), CLIENT_ID, jwks)
    hs = jwt.encode({"sub": "CHARACTER:EVE:1", "aud": CLIENT_ID, "iss": "login.eveonline.com", "exp": int(time.time()) + 60},
                    "secret-secret-secret-secret-secret", algorithm="HS256", headers={"kid": "kid-1"})
    with pytest.raises(LoginError):
        verify_access_token(hs, CLIENT_ID, jwks)
    for junk in ("", "a.b.c", "not-a-jwt"):
        with pytest.raises(LoginError):
            verify_access_token(junk, CLIENT_ID, jwks)


# ---- Rutas ---------------------------------------------------------------------------------------------------------

@pytest.fixture
def enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("USERS_DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setenv("USERS_ENC_KEYS", KEY_A)
    monkeypatch.setenv("EVE_LOGIN_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("EVE_LOGIN_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("EVE_LOGIN_CALLBACK_URL", "https://example.test/api/auth/callback")
    users_db.init_users_db()
    monkeypatch.setattr(auth_module.esi_auth, "exchange_code_for_token",
                        lambda cid, secret, code: {"access_token": "AT", "refresh_token": REFRESH})
    monkeypatch.setattr(auth_module, "verify_access_token",
                        lambda token, cid: (93000001, "Pilot One", list(REQUIRED_SCOPES)))
    return TestClient(app, follow_redirects=False)


def do_login(client):
    first = client.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}")
    state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
    return client.get(f"/api/auth/callback?code=abc&state={state}")


def test_disabled_by_default(tmp_path, monkeypatch):
    for name in ("EVE_LOGIN_CLIENT_ID", "EVE_LOGIN_CLIENT_SECRET", "USERS_ENC_KEYS"):
        monkeypatch.delenv(name, raising=False)
    c = TestClient(app, follow_redirects=False)
    body = c.get("/api/auth/status").json()
    assert body["enabled"] is False and body["authenticated"] is False
    assert c.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}").status_code == 503
    assert c.get("/api/auth/callback?code=a&state=b").status_code == 503
    assert c.delete("/api/auth/me").status_code == 503


def test_login_needs_the_current_consent_and_redirects_to_ccp(enabled):
    assert enabled.get("/api/auth/login").status_code == 400
    assert enabled.get("/api/auth/login?consent=old").status_code == 400
    r = enabled.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}")
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "login.eveonline.com" and q["client_id"] == [CLIENT_ID]
    assert q["scope"] == [" ".join(REQUIRED_SCOPES)] and q["redirect_uri"] == ["https://example.test/api/auth/callback"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api/auth" in cookie
    assert q["state"][0] in r.headers["set-cookie"] and r.headers["cache-control"] == "no-store"


def test_full_login_stores_an_encrypted_token_and_opens_a_session(enabled):
    r = do_login(enabled)
    assert r.status_code == 303 and r.headers["location"] == "/?login=ok"
    cookies = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("eve_session="))
    assert "httponly" in session_cookie.lower() and "samesite=lax" in session_cookie.lower()
    conn = users_db.connect()
    token = conn.execute("SELECT * FROM user_token").fetchone()
    assert REFRESH.encode() not in bytes(token["refresh_token_enc"])
    assert token_crypto.decrypt(bytes(token["refresh_token_enc"]), 93000001) == REFRESH
    assert token["scopes"] == " ".join(REQUIRED_SCOPES) and token["status"] == "ACTIVE"
    assert conn.execute("SELECT consent_version FROM user").fetchone()[0] == auth_module.CONSENT_VERSION
    conn.close()
    status = enabled.get("/api/auth/status").json()
    assert status["authenticated"] is True and status["character"] == {"id": 93000001, "name": "Pilot One"}
    assert status["needs_consent"] is False


def test_callback_rejects_missing_or_wrong_state_without_touching_the_db(enabled):
    enabled.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}")
    for qs in ("code=abc&state=forged", "code=abc", "state=x", ""):
        r = enabled.get(f"/api/auth/callback?{qs}")
        assert r.headers["location"] == "/?login=error"
    assert TestClient(app, follow_redirects=False).get("/api/auth/callback?code=a&state=b").headers["location"] == "/?login=error"
    conn = users_db.connect()
    assert conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 0
    conn.close()


def test_denied_by_the_user_and_failed_verification(enabled, monkeypatch):
    enabled.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}")
    assert enabled.get("/api/auth/callback?error=access_denied").headers["location"] == "/?login=denied"

    def boom(token, cid):
        raise LoginError("PyJWTError")
    monkeypatch.setattr(auth_module, "verify_access_token", boom)
    assert do_login(enabled).headers["location"] == "/?login=error"
    conn = users_db.connect()
    assert conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 0
    conn.close()


def test_state_cannot_be_reused_after_the_flow(enabled):
    first = enabled.get(f"/api/auth/login?consent={auth_module.CONSENT_VERSION}")
    state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
    assert enabled.get(f"/api/auth/callback?code=abc&state={state}").headers["location"] == "/?login=ok"
    assert enabled.get(f"/api/auth/callback?code=abc&state={state}").headers["location"] == "/?login=error"


def test_logout_removes_session_and_token(enabled):
    do_login(enabled)
    assert enabled.post("/api/auth/logout").status_code == 200
    assert enabled.get("/api/auth/status").json()["authenticated"] is False
    conn = users_db.connect()
    assert conn.execute("SELECT COUNT(*) FROM user_token").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM user_session").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] == 1      # la cuenta sigue; solo se retira el acceso
    conn.close()


def test_delete_me_erases_everything_and_export_requires_login(enabled):
    assert enabled.get("/api/auth/me/export").status_code == 401
    assert enabled.delete("/api/auth/me").status_code == 401
    do_login(enabled)
    exported = enabled.get("/api/auth/me/export").json()
    assert exported["user"]["character_id"] == 93000001 and "refresh_token_enc" not in json.dumps(exported)
    assert enabled.delete("/api/auth/me").status_code == 200
    conn = users_db.connect()
    assert all(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in ("user", "user_token", "user_session"))
    conn.close()
    assert enabled.get("/api/auth/status").json()["authenticated"] is False


def test_unsafe_requests_from_other_sites_are_refused(enabled):
    do_login(enabled)
    assert enabled.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert enabled.delete("/api/auth/me", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert enabled.get("/api/auth/status").json()["authenticated"] is True


def test_old_consent_asks_again(enabled):
    do_login(enabled)
    conn = users_db.connect()
    conn.execute("UPDATE user SET consent_version = 'ancient'")
    conn.commit()
    conn.close()
    assert enabled.get("/api/auth/status").json()["needs_consent"] is True


def test_forged_or_foreign_session_cookies_do_not_authenticate(enabled):
    do_login(enabled)
    other = TestClient(app, follow_redirects=False)
    other.cookies.set("eve_session", "forged")
    assert other.get("/api/auth/status").json()["authenticated"] is False
    assert other.get("/api/auth/me/export").status_code == 401


def test_secrets_never_reach_the_logs_or_responses(enabled, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    r = do_login(enabled)
    monkeypatch.setattr(auth_module, "verify_access_token", lambda t, c: (_ for _ in ()).throw(LoginError("x")))
    do_login(enabled)
    blob = caplog.text + r.text + json.dumps(dict(r.headers))
    assert REFRESH not in blob and "client-secret" not in blob


def test_tokens_with_a_missing_key_fail_closed(enabled, monkeypatch):
    monkeypatch.setenv("USERS_ENC_KEYS", "")
    body = enabled.get("/api/auth/status").json()
    assert body["enabled"] is False
    assert sqlite3.connect(os.environ["USERS_DB_PATH"]).execute("SELECT COUNT(*) FROM user_token").fetchone()[0] == 0


def test_privacy_page_explains_the_account_in_every_language(client):
    http, _db = client
    text = http.get("/privacy").text
    for marker in ("Optional EVE account", "Cuenta de EVE opcional", "Optionales EVE-Konto", "Compte EVE facultatif",
                   "Account EVE facoltativo"):
        assert marker in text
    assert text.count("12 ") >= 5
