import sqlite3

from tests.conftest import seed_item

TRENDS = {
    34: ("Tritanium", 0.12, "up", 0.05),
    35: ("Pyerite", -0.08, "down", 0.06),
    36: ("Mexallon", 0.01, "flat", 0.05),
    37: ("Isogen", None, "nodata", None),
    38: ("Nocxium", 0.30, "lowliq", 0.05),
}


def _seed(db_path):
    for type_id, (name, *_rest) in TRENDS.items():
        seed_item(db_path, type_id=type_id, name=name)
    conn = sqlite3.connect(db_path)
    for type_id, (_n, trend, label, threshold) in TRENDS.items():
        conn.execute(
            "UPDATE item_status SET price_trend = ?, price_trend_label = ?, price_trend_threshold = ? "
            "WHERE type_id = ?", (trend, label, threshold, type_id))
    conn.commit()
    conn.close()


def _names(response):
    return [i["name"] for i in response.json()["items"]]


def test_items_expose_the_trend_fields(client):
    api, db_path = client
    _seed(db_path)
    items = {i["type_id"]: i for i in api.get("/api/items").json()["items"]}
    assert items[34]["price_trend"] == 0.12 and items[34]["price_trend_label"] == "up"
    assert items[34]["price_trend_threshold"] == 0.05
    assert items[37]["price_trend"] is None and items[37]["price_trend_label"] == "nodata"
    assert api.get("/api/items/34").json()["status"]["price_trend_label"] == "up"


def test_sort_by_trend_puts_items_without_a_trend_last_in_both_directions(client):
    api, db_path = client
    _seed(db_path)
    desc = _names(api.get("/api/items", params={"sort": "price_trend", "order": "desc"}))
    asc = _names(api.get("/api/items", params={"sort": "price_trend", "order": "asc"}))
    assert desc == ["Nocxium", "Tritanium", "Mexallon", "Pyerite", "Isogen"]
    assert asc == ["Pyerite", "Mexallon", "Tritanium", "Nocxium", "Isogen"]


def test_filter_by_trend_label_and_by_range(client):
    api, db_path = client
    _seed(db_path)
    assert _names(api.get("/api/items", params={"trend": "down"})) == ["Pyerite"]
    assert _names(api.get("/api/items", params={"trend": "nodata"})) == ["Isogen"]
    both = _names(api.get("/api/items", params={"min_trend": 0.1, "sort": "price_trend", "order": "asc"}))
    assert both == ["Tritanium", "Nocxium"]
    assert _names(api.get("/api/items", params={"max_trend": -0.05})) == ["Pyerite"]


def test_unknown_trend_label_is_rejected_and_existing_filters_still_work(client):
    api, db_path = client
    _seed(db_path)
    assert api.get("/api/items", params={"trend": "sideways"}).status_code == 400
    assert api.get("/api/items", params={"min_roi": 0.1}).json()["total"] == 5
