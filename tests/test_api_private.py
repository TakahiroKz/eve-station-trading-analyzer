"""Cobertura de /api/private/* (T14): el chequeo de header (deps.require_cf_access_header)
y el comportamiento de cada ruta una vez pasado ese chequeo — wallet, recomendación en
vivo, órdenes propias, ajustes, y las dos acciones que hablan con la ESI real
(refresh/open-in-client), mockeadas para no pegarle a la red."""
import sqlite3

import pytest

from tests.conftest import FAKE_CF_HEADER, seed_item


@pytest.mark.parametrize("method,path", [
    ("get", "/api/private/auth/ping"),
    ("get", "/api/private/wallet"),
    ("get", "/api/private/character-orders"),
    ("get", "/api/private/character-orders/closed"),
    ("get", "/api/private/character-orders/fills"),
    ("get", "/api/private/settings"),
    ("post", "/api/private/character-orders/refresh"),
    ("post", "/api/private/settings/reset"),
])
def test_private_routes_reject_requests_without_cf_access_header(client, method, path):
    api_client, _ = client
    response = getattr(api_client, method)(path)
    assert response.status_code == 401


def test_private_routes_accept_a_well_formed_cf_access_header(client):
    api_client, _ = client
    response = api_client.get("/api/private/auth/ping", headers=FAKE_CF_HEADER)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_login_redirect_sends_the_browser_back_to_the_app(client):
    api_client, _ = client
    response = api_client.get("/api/private/login", headers=FAKE_CF_HEADER, follow_redirects=False)
    assert response.status_code == 200
    assert 'url=/"' in response.text


def test_wallet_endpoint_returns_the_live_balance_behind_the_header_check(client):
    api_client, _ = client
    response = api_client.get("/api/private/wallet", headers=FAKE_CF_HEADER)
    assert response.status_code == 200
    assert response.json() == {"wallet_balance": 1_234_567.0}


def test_item_recommendation_is_wallet_derived_and_gated(client):
    api_client, db_path = client
    seed_item(db_path)

    # Sin el header de Access, ni siquiera llega a calcularse.
    assert api_client.get("/api/private/items/34/recommendation").status_code == 401

    response = api_client.get("/api/private/items/34/recommendation", headers=FAKE_CF_HEADER)
    assert response.status_code == 200
    body = response.json()
    assert body["unidades_sugeridas"] is not None


def test_item_recommendation_is_none_without_a_market_snapshot(client):
    api_client, db_path = client
    seed_item(db_path, type_id=35, name="Pyerite")
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM market_snapshot WHERE type_id = 35")
    conn.commit()
    conn.close()

    response = api_client.get("/api/private/items/35/recommendation", headers=FAKE_CF_HEADER)
    assert response.status_code == 200
    assert response.json() is None


def test_item_recommendation_404_for_unknown_item(client):
    api_client, _ = client
    response = api_client.get("/api/private/items/999/recommendation", headers=FAKE_CF_HEADER)
    assert response.status_code == 404


def test_character_orders_lists_are_empty_by_default(client):
    api_client, _ = client
    for path in ("/character-orders", "/character-orders/closed", "/character-orders/fills"):
        response = api_client.get(f"/api/private{path}", headers=FAKE_CF_HEADER)
        assert response.status_code == 200
        assert response.json() == []


def test_settings_list_includes_seeded_defaults(client):
    api_client, _ = client
    response = api_client.get("/api/private/settings", headers=FAKE_CF_HEADER)
    assert response.status_code == 200
    keys = {row["key"] for row in response.json()}
    assert "min_daily_order_count_7d" in keys


def test_settings_update_rejects_negative_value(client):
    api_client, _ = client
    response = api_client.put(
        "/api/private/settings/min_daily_volume_7d", json={"value": -1}, headers=FAKE_CF_HEADER,
    )
    assert response.status_code == 422


def test_settings_update_rejects_zero_for_a_strictly_positive_key(client):
    api_client, _ = client
    response = api_client.put(
        "/api/private/settings/min_daily_order_count_7d", json={"value": 0}, headers=FAKE_CF_HEADER,
    )
    assert response.status_code == 422


def test_settings_update_404_for_unknown_key(client):
    api_client, _ = client
    response = api_client.put(
        "/api/private/settings/no_existe", json={"value": 1}, headers=FAKE_CF_HEADER,
    )
    assert response.status_code == 404


def test_settings_update_persists_the_new_value(client):
    api_client, _ = client
    response = api_client.put(
        "/api/private/settings/min_daily_volume_7d", json={"value": 42}, headers=FAKE_CF_HEADER,
    )
    assert response.status_code == 200
    assert response.json()["value"] == 42

    listed = api_client.get("/api/private/settings", headers=FAKE_CF_HEADER).json()
    row = next(r for r in listed if r["key"] == "min_daily_volume_7d")
    assert row["value"] == 42


def test_settings_reset_restores_default_values(client):
    api_client, _ = client
    api_client.put("/api/private/settings/min_daily_volume_7d", json={"value": 42}, headers=FAKE_CF_HEADER)

    response = api_client.post("/api/private/settings/reset", headers=FAKE_CF_HEADER)
    assert response.status_code == 200
    row = next(r for r in response.json() if r["key"] == "min_daily_volume_7d")
    assert row["value"] == row["default_value"]


def test_refresh_character_orders_without_esi_session_returns_409(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr("backend.api.private.get_valid_session", lambda: None)
    response = api_client.post("/api/private/character-orders/refresh", headers=FAKE_CF_HEADER)
    assert response.status_code == 409


def test_refresh_character_orders_calls_the_positions_engine_when_authorized(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr("backend.api.private.get_valid_session", lambda: ("token", 123))
    calls = []
    monkeypatch.setattr(
        "backend.api.private.check_character_orders",
        lambda client, db_path, notify: calls.append((db_path, notify)),
    )

    response = api_client.post("/api/private/character-orders/refresh", headers=FAKE_CF_HEADER)

    assert response.status_code == 200
    assert response.json() == []
    assert len(calls) == 1
    assert calls[0][1] is False  # notify=False: refresco manual, sin duplicar Telegram.


def test_open_in_client_without_esi_session_returns_409(client, monkeypatch):
    api_client, db_path = client
    seed_item(db_path)
    monkeypatch.setattr("backend.api.private.get_valid_session", lambda: None)
    response = api_client.post("/api/private/items/34/open-in-client", headers=FAKE_CF_HEADER)
    assert response.status_code == 409


def test_open_in_client_opens_the_window_when_authorized(client, monkeypatch):
    api_client, db_path = client
    seed_item(db_path)
    monkeypatch.setattr("backend.api.private.get_valid_session", lambda: ("token", 123))
    calls = []
    monkeypatch.setattr(
        "ingestion.esi_client.EsiClient.open_market_window",
        lambda self, type_id, access_token: calls.append((type_id, access_token)),
    )

    response = api_client.post("/api/private/items/34/open-in-client", headers=FAKE_CF_HEADER)

    assert response.status_code == 200
    assert response.json()["opened"] is True
    assert calls == [(34, "token")]
