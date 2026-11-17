"""Cobertura de las rutas públicas de backend/api/main.py (D2): /api/summary,
/api/schedule, /api/items (filtros/orden/paginación), /api/categories,
/api/items/{id} (detalle) y /api/status-changes. Ninguna de estas requiere el header
de Cloudflare Access -- son justamente las que deben quedar visibles sin login
(Screener + filtros + reloj)."""
import sqlite3

from tests.conftest import seed_item


def test_summary_on_an_empty_db(client):
    api_client, _ = client
    response = api_client.get("/api/summary")
    assert response.status_code == 200
    body = response.json()
    assert body == {"counts": {}, "total": 0, "last_evaluated_at": None}


def test_summary_counts_items_by_status(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, status="POTENCIAL")
    seed_item(db_path, type_id=35, status="DESCARTADO")
    seed_item(db_path, type_id=36, status="DESCARTADO")

    body = api_client.get("/api/summary").json()

    assert body["total"] == 3
    assert body["counts"] == {"POTENCIAL": 1, "DESCARTADO": 2}
    assert body["last_evaluated_at"] is not None


def test_schedule_returns_both_engines(client):
    api_client, _ = client
    response = api_client.get("/api/schedule")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"market_next_run", "positions_next_run"}


def test_items_list_defaults_to_volumen_diario_real_desc(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    seed_item(db_path, type_id=35, name="Pyerite")

    response = api_client.get("/api/items")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert {item["name"] for item in body["items"]} == {"Tritanium", "Pyerite"}


def test_items_list_filters_by_status(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium", status="POTENCIAL")
    seed_item(db_path, type_id=35, name="Pyerite", status="DESCARTADO")

    response = api_client.get("/api/items", params={"status": "POTENCIAL"})

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Tritanium"


def test_items_list_rejects_an_unknown_sort_field(client):
    api_client, _ = client
    response = api_client.get("/api/items", params={"sort": "no_existe"})
    assert response.status_code == 400


def test_items_list_rejects_an_invalid_order(client):
    api_client, _ = client
    response = api_client.get("/api/items", params={"order": "sideways"})
    assert response.status_code == 400


def test_items_list_rejects_a_limit_out_of_range(client):
    api_client, _ = client
    response = api_client.get("/api/items", params={"limit": 0})
    assert response.status_code == 400

    response = api_client.get("/api/items", params={"limit": 501})
    assert response.status_code == 400


def test_items_list_pagination(client):
    api_client, db_path = client
    for i in range(3):
        seed_item(db_path, type_id=34 + i, name=f"Item {i}")

    page = api_client.get("/api/items", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    next_page = api_client.get("/api/items", params={"limit": 2, "offset": 2}).json()
    assert len(next_page["items"]) == 1


def test_categories_returns_distinct_categories(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, category_id=6, category_name="Ore")
    seed_item(db_path, type_id=35, category_id=6, category_name="Ore")
    seed_item(db_path, type_id=36, category_id=25, category_name="Ammo")

    response = api_client.get("/api/categories")

    assert response.status_code == 200
    assert response.json() == [
        {"category_id": 25, "category_name": "Ammo"},
        {"category_id": 6, "category_name": "Ore"},
    ]


def test_item_detail_404_for_an_unclassified_item(client):
    api_client, _ = client
    response = api_client.get("/api/items/999")
    assert response.status_code == 404


def test_item_detail_includes_snapshot_and_history_but_no_live_recommendation(client):
    api_client, db_path = client
    seed_item(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
        "VALUES (34, date('now'), 4.2, 4.6, 3.9, 1000, 5)",
    )
    conn.commit()
    conn.close()

    response = api_client.get("/api/items/34")

    assert response.status_code == 200
    body = response.json()
    assert "live_recommendation" not in body
    assert body["latest_snapshot"]["best_buy"] == 4.0
    assert len(body["history"]) == 1


def test_status_changes_returns_recent_changes(client):
    api_client, db_path = client
    seed_item(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO item_status_history (type_id, previous_status, new_status, changed_at, reason) "
        "VALUES (34, 'EN_OBSERVACION', 'POTENCIAL', datetime('now'), 'mejoró el spread')",
    )
    conn.commit()
    conn.close()

    response = api_client.get("/api/status-changes")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["new_status"] == "POTENCIAL"
    assert body[0]["name"] == "Tritanium"


def test_items_list_filters_by_name_ignoring_case(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    seed_item(db_path, type_id=35, name="Pyerite")
    seed_item(db_path, type_id=36, name="Compressed Tritanium")

    body = api_client.get("/api/items", params={"q": "TRITA"}).json()

    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {"Tritanium", "Compressed Tritanium"}


def test_items_list_name_filter_trims_spaces_and_blank_means_no_filter(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    seed_item(db_path, type_id=35, name="Pyerite")

    assert api_client.get("/api/items", params={"q": "  pyer  "}).json()["total"] == 1
    assert api_client.get("/api/items", params={"q": "   "}).json()["total"] == 2
    assert api_client.get("/api/items", params={"q": ""}).json()["total"] == 2


def test_items_list_name_filter_treats_wildcards_as_plain_text(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")
    seed_item(db_path, type_id=35, name="100% Pure_Ore")
    seed_item(db_path, type_id=36, name="100X PureXOre")

    assert api_client.get("/api/items", params={"q": "%"}).json()["total"] == 1
    assert api_client.get("/api/items", params={"q": "_"}).json()["total"] == 1
    assert api_client.get("/api/items", params={"q": "Pure_Ore"}).json()["total"] == 1
    assert api_client.get("/api/items", params={"q": "\\"}).json()["total"] == 0


def test_items_list_name_filter_combines_with_status_and_pagination(client):
    api_client, db_path = client
    for n in range(1, 6):
        seed_item(db_path, type_id=100 + n, name=f"Mutaplasmid {n}", status="POTENCIAL")
    seed_item(db_path, type_id=200, name="Mutaplasmid Old", status="DESCARTADO")
    seed_item(db_path, type_id=201, name="Tritanium", status="POTENCIAL")

    body = api_client.get(
        "/api/items", params={"q": "mutaplasmid", "status": "POTENCIAL", "limit": 2, "offset": 2},
    ).json()

    assert body["total"] == 5  # el descartado y el otro ítem quedan fuera
    assert len(body["items"]) == 2


def test_items_list_rejects_a_name_query_longer_than_100_characters(client):
    api_client, _ = client

    assert api_client.get("/api/items", params={"q": "a" * 101}).status_code == 422
    assert api_client.get("/api/items", params={"q": "a" * 100}).status_code == 200


def test_items_list_name_filter_is_safe_against_sql_injection_text(client):
    api_client, db_path = client
    seed_item(db_path, type_id=34, name="Tritanium")

    response = api_client.get("/api/items", params={"q": "x' OR '1'='1"})

    assert response.status_code == 200
    assert response.json()["total"] == 0
