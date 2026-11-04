"""Fase 1 de SEO_PLAN.md: páginas HTML por ítem, índice y sitemap dinámico."""

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
    assert "<h1>Tritanium — station trading in Jita</h1>" in page
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
    assert "Material (2)" in page


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
