"""Auditoría de seguridad del 2026-11-04: cabeceras, CSRF, verificación del JWT de Access,
topes de parámetros, valores no finitos, permisos del refresh token y escape del JSON-LD."""
import os
import time

import pytest
import rsa
from google.auth import crypt, jwt

from backend.api import security
from storage.settings_registry import SETTINGS_BY_KEY
from tests.conftest import FAKE_CF_HEADER, seed_item

AUD = "aud-tag-de-prueba"
TEAM = "https://equipo.cloudflareaccess.com"


def test_security_headers_on_every_response(client):
    http, _ = client
    response = http.get("/api/summary")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "script-src 'self' https://static.cloudflareinsights.com" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_hsts_only_when_the_request_came_over_https(client):
    http, _ = client
    response = http.get("/api/summary", headers={"x-forwarded-proto": "https"})
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_cross_origin_post_to_private_routes_is_rejected(client):
    http, _ = client
    evil = {**FAKE_CF_HEADER, "Origin": "https://evil.example"}
    assert http.post("/api/private/settings/reset", headers=evil).status_code == 403
    cross_site = {**FAKE_CF_HEADER, "Sec-Fetch-Site": "cross-site"}
    assert http.post("/api/private/settings/reset", headers=cross_site).status_code == 403
    own = {**FAKE_CF_HEADER, "Origin": "https://evemarket-analyzer.online"}
    assert http.post("/api/private/settings/reset", headers=own).status_code == 200
    assert http.post("/api/private/settings/reset", headers=FAKE_CF_HEADER).status_code == 200


@pytest.fixture
def signing_key(monkeypatch):
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", TEAM)
    public, private = rsa.newkeys(2048)
    pem_private = private.save_pkcs1("PEM")
    monkeypatch.setattr(
        security, "_access_certs",
        lambda team_url: {"k1": public.save_pkcs1("PEM").decode()},
    )
    signer = crypt.RSASigner.from_string(pem_private, key_id="k1")

    def make(aud=AUD, iss=TEAM, exp_delta=300):
        now = int(time.time())
        return jwt.encode(signer, {"aud": [aud], "iss": iss, "iat": now, "exp": now + exp_delta})
    return make


def _auth(token):
    return {"Cf-Access-Jwt-Assertion": token if isinstance(token, str) else token.decode()}


def test_forged_jwt_is_rejected_when_the_audience_is_configured(client, monkeypatch, signing_key):
    http, _ = client
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    assert http.get("/api/private/auth/ping", headers=FAKE_CF_HEADER).status_code == 401
    assert http.get("/api/private/auth/ping", headers=_auth(signing_key())).status_code == 200
    assert http.get("/api/private/auth/ping", headers=_auth(signing_key(aud="otra"))).status_code == 401
    assert http.get("/api/private/auth/ping", headers=_auth(signing_key(exp_delta=-600))).status_code == 401
    forged_issuer = signing_key(iss="https://atacante.example.com")
    assert http.get("/api/private/auth/ping", headers=_auth(forged_issuer)).status_code == 401


def test_observation_mode_logs_but_does_not_block(client, monkeypatch, caplog):
    http, _ = client
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    monkeypatch.setenv("CF_ACCESS_ENFORCE", "0")
    with caplog.at_level("WARNING"):
        assert http.get("/api/private/auth/ping", headers=FAKE_CF_HEADER).status_code == 200
    assert "NO verificada" in caplog.text


def test_unbounded_query_parameters_are_rejected(client):
    http, _ = client
    assert http.get("/api/status-changes?limit=100000000").status_code == 400
    assert http.get("/api/items?offset=-1").status_code == 400
    assert http.get("/api/items?offset=999999999").status_code == 400
    assert http.get("/api/private/character-orders/closed?limit=0", headers=FAKE_CF_HEADER).status_code == 400
    assert http.get("/api/private/character-orders/fills?limit=99999", headers=FAKE_CF_HEADER).status_code == 400


def test_non_finite_or_absurd_setting_values_are_rejected(client):
    http, _ = client
    key = next(iter(SETTINGS_BY_KEY))
    headers = {**FAKE_CF_HEADER, "Content-Type": "application/json"}
    for body in (b'{"value": NaN}', b'{"value": Infinity}', b'{"value": 1e13}'):
        assert http.put(f"/api/private/settings/{key}", content=body, headers=headers).status_code == 422


@pytest.mark.skipif(os.name == "nt", reason="los permisos POSIX no aplican en Windows")
def test_refresh_token_file_is_owner_only(tmp_path):
    from ingestion.esi_auth import save_refresh_token

    path = tmp_path / "creds" / "token.txt"
    save_refresh_token(str(path), "secreto")
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_json_ld_cannot_break_out_of_its_script_tag(client):
    http, db_path = client
    seed_item(db_path, 77, "Evil</script><img src=x onerror=alert(1)>&<!--", "POTENCIAL",
              category_id=4, category_name="Material")
    page = http.get("/items/77-evil").text
    assert "<img src=x" not in page
    assert page.count("</script>") == 2  # the JSON-LD block and /analytics.js
    assert "<!--" not in page


def test_unpinned_issuer_is_never_trusted(client, monkeypatch, signing_key):
    http, _ = client
    monkeypatch.setenv("CF_ACCESS_AUD", AUD)
    token = signing_key()
    assert http.get("/api/private/auth/ping", headers=_auth(token)).status_code == 200
    monkeypatch.delenv("CF_ACCESS_TEAM_DOMAIN")  # sin dominio de equipo configurado: cerrado
    assert http.get("/api/private/auth/ping", headers=_auth(token)).status_code == 401


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    http, _ = client
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    ip = {"CF-Connecting-IP": "203.0.113.7"}
    assert [http.get("/api/summary", headers=ip).status_code for _ in range(3)] == [200, 200, 200]
    blocked = http.get("/api/summary", headers=ip)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert http.get("/api/summary", headers={"CF-Connecting-IP": "203.0.113.8"}).status_code == 200
    assert http.get("/robots.txt", headers=ip).status_code != 429  # solo /api/*


def test_rate_limit_window_slides():
    from backend.api import ratelimit

    ratelimit.reset()
    assert ratelimit.check_rate_limit("1.1.1.1", 2, now=0.0) is None
    assert ratelimit.check_rate_limit("1.1.1.1", 2, now=1.0) is None
    assert ratelimit.check_rate_limit("1.1.1.1", 2, now=2.0) is not None
    assert ratelimit.check_rate_limit("1.1.1.1", 2, now=61.0) is None
    ratelimit.reset()
