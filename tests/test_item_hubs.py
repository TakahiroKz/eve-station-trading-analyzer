"""SEO: la ficha de ítem compara el ítem en los hubs activos y las portadas de mercado enlazan a ella."""
import sqlite3

from tests.conftest import seed_item


def _hub_row(db_path, market_id, type_id, roi=0.2, trades=100.0, status="POTENCIAL",
             evaluated="datetime('now')", trend_label="nodata", trend=None):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR IGNORE INTO item_type (type_id, name) VALUES (?, 'Tritanium')", (type_id,))
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = ?", (market_id,))
    conn.execute(
        "INSERT INTO item_status (market_id, type_id, status, reason, spread_bruto, evaluacion_spread, "
        "liquidez, roi, best_buy, best_sell, volumen_diario_real, avg_daily_order_count_7d, "
        f"price_trend, price_trend_label, last_evaluated_at) "
        f"VALUES (?, ?, ?, 'ok', 0.1, 'buena', 'alta', ?, 4.0, 4.5, 1000, ?, ?, ?, {evaluated})",
        (market_id, type_id, status, roi, trades, trend, trend_label),
    )
    conn.commit()
    conn.close()


def _row_of(page, hub_name):
    start = page.index(f'">{hub_name}</a></td>')
    return page[start: page.index("</tr>", start)]


def test_item_page_compares_active_hubs_and_dashes_the_ones_without_data(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")  # Jita
    _hub_row(db_path, "amarr", 34, roi=0.5, trades=300.0, trend_label="up", trend=0.12)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = 'hek'")  # active, no row for the item
    conn.commit()
    conn.close()

    page = http.get("/items/34-tritanium").text

    assert "<h2>Prices across the trade hubs</h2>" in page
    amarr = _row_of(page, "Amarr")
    assert "50.0%" in amarr and "300" in amarr and "Rising +12.0%" in amarr
    assert _row_of(page, "Hek").count("—") == 6
    assert '<td><a href="/dodixie/">' not in page and '<td><a href="/rens/">' not in page  # inactive hubs are not rows
    assert "<h1>Tritanium — station trading in EVE's trade hubs</h1>" in page
    assert "<title>Tritanium: price and ROI in EVE&#x27;s trade hubs | EveMarket</title>" in page
    assert '<meta name="robots" content="index, follow">' in page


def test_summary_sentence_names_the_best_roi_and_the_busiest_hub(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")  # Jita: roi 0.2, 1000 volume
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE item_status SET avg_daily_order_count_7d = 800 WHERE market_id = 'jita'")
    conn.commit()
    conn.close()
    _hub_row(db_path, "amarr", 34, roi=0.5, trades=300.0)

    page = http.get("/items/34-tritanium").text

    assert ("Right now the highest ROI for Tritanium is in Amarr (50.0%) and the most traded hub "
            "is Jita (800 trades per day).") in page


def test_stale_hub_data_is_not_published(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")
    _hub_row(db_path, "amarr", 34, roi=0.9, trades=999.0, evaluated="datetime('now', '-3 hours')")

    page = http.get("/items/34-tritanium").text

    assert _row_of(page, "Amarr").count("—") == 6
    assert "90.0%" not in page
    assert "Right now" not in page  # only one hub with fresh data: no comparison sentence


def test_market_page_links_items_that_are_jita_candidates_only(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")  # candidate in Jita
    _hub_row(db_path, "amarr", 34, trades=500.0)
    _hub_row(db_path, "amarr", 35, trades=400.0)  # only in Amarr: no item page to link to

    page = http.get("/amarr/").text

    assert 'href="/items/34-tritanium"' in page
    assert "/items/35-" not in page
