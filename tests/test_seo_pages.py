"""SEO: páginas HTML por ítem, índice y sitemap dinámico."""
import sqlite3

from backend.api.pages import item_path, slugify
from tests.conftest import seed_item


def test_slugify_and_item_path():
    assert slugify("Compressed Scordite III-Grade") == "compressed-scordite-iii-grade"
    assert slugify("!!!") == "item"
    assert item_path(34, "Tritanium") == "/items/34-tritanium"


def test_item_page_renders_content_in_the_raw_html(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL", category_id=4, category_name="Material")

    response = http.get("/items/34-tritanium")

    assert response.status_code == 200
    page = response.text
    assert "<h1>Tritanium — station trading in EVE's trade hubs</h1>" in page
    assert '<link rel="canonical" href="https://evemarket-analyzer.online/items/34-tritanium">' in page
    assert '<meta name="robots" content="index, follow">' in page
    assert "Potential" in page and "4.00 ISK" in page and "4.50 ISK" in page
    assert "application/ld+json" in page and "BreadcrumbList" in page
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_non_indexable_status_is_noindex(client):
    http, db_path = client
    seed_item(db_path, 35, "Pyerite", "DESCARTADO")

    page = http.get("/items/35-pyerite").text

    assert '<meta name="robots" content="noindex, follow">' in page


def test_wrong_slug_redirects_to_the_canonical_url(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")

    for ref in ("34", "34-wrong-slug"):
        response = http.get(f"/items/{ref}", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/items/34-tritanium"


def test_unknown_or_malformed_items_are_404_and_noindex(client):
    http, _ = client
    for ref in ("999999-nothing", "abc"):
        response = http.get(f"/items/{ref}")
        assert response.status_code == 404
        assert '<meta name="robots" content="noindex">' in response.text


def test_item_names_are_html_escaped(client):
    http, db_path = client
    seed_item(db_path, 77, '<script>alert(1)</script> & "Co"', "POTENCIAL")

    ref = item_path(77, '<script>alert(1)</script> & "Co"')
    page = http.get(ref).text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_items_index_lists_only_indexable_items_grouped_by_category(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL", category_id=4, category_name="Material")
    seed_item(db_path, 35, "Pyerite", "POTENCIAL_SIN_ORDENES", category_id=4, category_name="Material")
    seed_item(db_path, 36, "Mexallon", "DESCARTADO", category_id=4, category_name="Material")

    page = http.get("/items").text

    assert "/items/34-tritanium" in page and "/items/35-pyerite" in page
    assert "mexallon" not in page.lower()
    assert '<h2>Material</h2><span class="count">2</span>' in page
    assert "Material · 2" in page


def test_sitemap_contains_home_hub_and_only_indexable_items(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")
    seed_item(db_path, 36, "Mexallon", "DESCARTADO")

    response = http.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    xml = response.text
    assert "<loc>https://evemarket-analyzer.online/</loc>" in xml
    assert "<loc>https://evemarket-analyzer.online/items</loc>" in xml
    assert "<loc>https://evemarket-analyzer.online/items/34-tritanium</loc>" in xml
    assert "mexallon" not in xml
    assert 'hreflang="de" href="https://evemarket-analyzer.online/de/"' in xml
    assert '<loc>https://evemarket-analyzer.online/de/</loc>' in xml
    assert '?lang=' not in xml


def test_sitemap_item_lastmod_is_the_last_status_change_not_the_last_evaluation(client):
    import sqlite3

    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")   # evaluated "now", status changed long ago
    seed_item(db_path, 35, "Pyerite", "POTENCIAL")     # no history row at all
    conn = sqlite3.connect(db_path)
    for changed_at in ("2026-10-01T08:00:00+00:00", "2026-11-05T09:30:00+00:00"):
        conn.execute(
            "INSERT INTO item_status_history (type_id, previous_status, new_status, changed_at, reason) "
            "VALUES (34, NULL, 'POTENCIAL', ?, 'ok')", (changed_at,),
        )
    conn.commit()
    conn.close()

    xml = http.get("/sitemap.xml").text

    assert (
        "<loc>https://evemarket-analyzer.online/items/34-tritanium</loc>"
        "<lastmod>2026-11-05</lastmod>"
    ) in xml
    assert "<loc>https://evemarket-analyzer.online/items/35-pyerite</loc><changefreq>" in xml


def test_indexnow_key_file_is_served_and_does_not_shadow_other_txt(client):
    from backend.api.indexnow import INDEXNOW_KEY

    http, _ = client
    response = http.get(f"/{INDEXNOW_KEY}.txt")

    assert response.status_code == 200
    assert response.text == INDEXNOW_KEY
    assert http.get("/otra-clave.txt").text != INDEXNOW_KEY


def test_an_item_without_sell_orders_says_so_in_english_and_shows_no_roi(client):
    from analytics.classification import NO_DATA_LIQUIDITY, NO_PRICE_SPREAD, UNEVALUATED_REASONS
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "DESCARTADO")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE item_status SET reason = ?, evaluacion_spread = ?, liquidez = ?, best_sell = 0, roi = 0, "
                 "spread_bruto = 0 WHERE type_id = 34",
                 (UNEVALUATED_REASONS["no_sell"], NO_PRICE_SPREAD, NO_DATA_LIQUIDITY))
    conn.commit()
    conn.close()

    page = http.get("/items/34-tritanium").text

    assert "there are no sell orders, so there is no sell price to evaluate it." in page
    assert "The best buy order is 4.00 ISK; there are no sell orders." in page
    assert "0.00 ISK" not in page and "0.0%" not in page
    assert "No price" in page and "No data" in page
    assert NO_PRICE_SPREAD not in page and NO_DATA_LIQUIDITY not in page and "its spread is losing" not in page
