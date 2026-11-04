"""Fase 0 de SEO_PLAN.md: docs apagadas, redirecciones canónicas, cabeceras de caché e
indexación."""
from backend.api.seo import IMMUTABLE_CACHE, cache_control_for, canonical_redirect


def test_api_docs_are_not_published_by_default(client):
    http, _ = client
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert http.get(path).status_code == 404


def test_api_responses_are_marked_noindex(client):
    http, _ = client
    response = http.get("/api/summary")
    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_http_request_on_the_production_host_redirects_to_https(client):
    http, _ = client
    response = http.get(
        "/api/summary?x=1", follow_redirects=False,
        headers={"host": "evemarket-analyzer.online", "x-forwarded-proto": "http"},
    )
    assert response.status_code == 301
    assert response.headers["location"] == "https://evemarket-analyzer.online/api/summary?x=1"


def test_www_host_redirects_to_the_apex_over_https(client):
    http, _ = client
    response = http.get(
        "/", follow_redirects=False,
        headers={"host": "www.evemarket-analyzer.online", "x-forwarded-proto": "https"},
    )
    assert response.status_code == 301
    assert response.headers["location"] == "https://evemarket-analyzer.online/"


def test_canonical_https_request_and_local_hosts_are_not_redirected(client):
    http, _ = client
    ok = http.get(
        "/api/summary", follow_redirects=False,
        headers={"host": "evemarket-analyzer.online", "x-forwarded-proto": "https"},
    )
    local = http.get("/api/summary", follow_redirects=False, headers={"host": "localhost:8001"})
    assert ok.status_code == 200
    assert local.status_code == 200


def test_canonical_redirect_ignores_unknown_hosts():
    assert canonical_redirect("example.com", "http", "/") is None
    assert canonical_redirect("localhost:8001", "http", "/") is None


def test_cache_control_policy():
    assert cache_control_for("/assets/index-abc.js", "text/javascript", 200) == IMMUTABLE_CACHE
    assert cache_control_for("/", "text/html; charset=utf-8", 200) == "no-cache"
    assert cache_control_for("/assets/index-abc.js", "text/javascript", 404) is None
    assert cache_control_for("/api/summary", "application/json", 200) is None


def test_language_root_without_trailing_slash_redirects_in_one_hop(client):
    http, _ = client
    response = http.get(
        "/es", follow_redirects=False,
        headers={"host": "evemarket-analyzer.online", "x-forwarded-proto": "https"},
    )
    assert response.status_code == 301
    assert response.headers["location"] == "https://evemarket-analyzer.online/es/"


def test_language_root_with_slash_is_left_alone():
    assert canonical_redirect("evemarket-analyzer.online", "https", "/de/") is None
    assert canonical_redirect("evemarket-analyzer.online", "https", "/de?x=1") == (
        "https://evemarket-analyzer.online/de/?x=1"
    )


def test_head_requests_are_served_like_get_without_body(client):
    http, _ = client
    for path in ("/api/summary", "/api/schedule"):
        get = http.get(path)
        head = http.head(path)
        assert head.status_code == get.status_code == 200
        assert head.content == b""
        assert head.headers["content-type"] == get.headers["content-type"]
