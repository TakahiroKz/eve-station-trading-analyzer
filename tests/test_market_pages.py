"""SEO: portadas públicas por mercado (/amarr/, /es/amarr/, ...) y su entrada en el sitemap."""
import sqlite3

from backend.api.market_pages import MARKET_SLUGS, market_path
from tests.conftest import seed_item


def _seed_market_item(db_path, market_id, type_id, name, status="POTENCIAL", trades=100.0,
                      evaluated="datetime('now')"):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR IGNORE INTO item_type (type_id, name) VALUES (?, ?)", (type_id, name))
    conn.execute(
        "INSERT INTO item_status (market_id, type_id, status, reason, spread_bruto, evaluacion_spread, "
        "liquidez, roi, best_buy, best_sell, volumen_diario_real, avg_daily_order_count_7d, "
        f"last_evaluated_at) VALUES (?, ?, ?, 'ok', 0.1, 'buena', 'alta', 0.2, 4.0, 4.5, 1000, ?, {evaluated})",
        (market_id, type_id, status, trades),
    )
    conn.commit()
    conn.close()


def _enable(db_path, market_id):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id = ?", (market_id,))
    conn.commit()
    conn.close()


def test_market_path_english_at_the_root_and_other_languages_under_their_prefix():
    assert market_path("en", "amarr") == "/amarr/"
    assert market_path("es", "amarr") == "/es/amarr/"
    assert MARKET_SLUGS == ("jita", "amarr", "dodixie", "rens", "hek")


def test_jita_market_page_renders_real_content_in_the_raw_html(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")

    response = http.get("/jita/")

    assert response.status_code == 200
    page = response.text
    assert "<h1>Station trading in Jita: items worth trading</h1>" in page
    assert '<link rel="canonical" href="https://evemarket-analyzer.online/jita/">' in page
    assert '<meta name="robots" content="index, follow">' in page
    assert 'href="/items/34-tritanium"' in page  # Jita items have their own page
    assert 'href="/?market=jita"' in page
    assert page.count('rel="alternate" hreflang=') == 6  # 5 languages + x-default
    assert 'hreflang="es" href="https://evemarket-analyzer.online/es/jita/"' in page
    assert "BreadcrumbList" in page
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_inactive_market_is_404_and_noindex(client):
    http, _ = client

    response = http.get("/amarr/")

    assert response.status_code == 404
    assert '<meta name="robots" content="noindex">' in response.text


def test_active_market_lists_its_top_items_without_item_links(client):
    http, db_path = client
    _enable(db_path, "amarr")
    _seed_market_item(db_path, "amarr", 34, "Tritanium", trades=50)
    _seed_market_item(db_path, "amarr", 35, "Pyerite", trades=900)
    _seed_market_item(db_path, "amarr", 36, "Mexallon", status="DESCARTADO", trades=5000)

    page = http.get("/amarr/").text

    assert "Domain" in page
    assert page.index("Pyerite") < page.index("Tritanium")  # ranked by trades per day
    assert "Mexallon" not in page  # not an indexable status
    assert "/items/" not in page  # per-item pages are Jita only for now
    assert '<link rel="canonical" href="https://evemarket-analyzer.online/amarr/">' in page


def test_localized_page_uses_its_language_and_canonical(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")

    page = http.get("/es/jita/").text

    assert '<html lang="es">' in page
    assert "<h1>Station trading en Jita: ítems que conviene comerciar</h1>" in page
    assert '<link rel="canonical" href="https://evemarket-analyzer.online/es/jita/">' in page
    assert 'href="/es/?market=jita"' in page
    assert '"inLanguage": "es"' in page


def test_all_languages_and_markets_have_a_route(client):
    http, db_path = client
    for slug in MARKET_SLUGS:
        _enable(db_path, slug)
    for lang in ("en", "es", "de", "fr", "it"):
        for slug in MARKET_SLUGS:
            assert http.get(market_path(lang, slug)).status_code == 200


def test_market_without_candidates_or_with_stale_data_is_noindex(client):
    http, db_path = client
    _enable(db_path, "amarr")
    _enable(db_path, "hek")
    _seed_market_item(db_path, "amarr", 34, "Tritanium", status="DESCARTADO")
    _seed_market_item(db_path, "hek", 35, "Pyerite", evaluated="datetime('now', '-3 hours')")

    assert '<meta name="robots" content="noindex, follow">' in http.get("/amarr/").text
    assert '<meta name="robots" content="noindex, follow">' in http.get("/hek/").text


def test_market_item_names_are_html_escaped(client):
    http, db_path = client
    _enable(db_path, "amarr")
    _seed_market_item(db_path, "amarr", 77, '<script>alert(1)</script> & "Co"')

    page = http.get("/amarr/").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_sitemap_lists_market_pages_only_for_active_markets_with_candidates(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")
    _enable(db_path, "amarr")
    _enable(db_path, "rens")
    _seed_market_item(db_path, "amarr", 35, "Pyerite")
    _seed_market_item(db_path, "rens", 36, "Mexallon", status="DESCARTADO")

    xml = http.get("/sitemap.xml").text

    for lang_path in ("/jita/", "/es/jita/", "/amarr/", "/it/amarr/"):
        assert f"<loc>https://evemarket-analyzer.online{lang_path}</loc>" in xml
    assert "/rens/" not in xml and "/dodixie/" not in xml and "/hek/" not in xml
    assert 'hreflang="de" href="https://evemarket-analyzer.online/de/amarr/"' in xml


def test_every_server_page_links_to_all_market_pages_in_its_language(client):
    http, db_path = client
    seed_item(db_path, 34, "Tritanium", "POTENCIAL")

    for path, prefix in (("/items", ""), ("/items/34-tritanium", ""), ("/es/jita/", "/es")):
        page = http.get(path).text
        for slug in MARKET_SLUGS:
            assert f'<a href="{prefix}/{slug}/">' in page, (path, slug)
