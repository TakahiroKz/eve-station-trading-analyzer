"""Páginas HTML públicas generadas en el servidor (Fase 1 de SEO_PLAN.md): una por ítem
(`/items/{id}-{slug}`), un índice (`/items`) y el `sitemap.xml` dinámico.

La PWA pinta todo con JavaScript desde /api/ (bloqueado en robots.txt), así que para los
buscadores y los asistentes con IA el sitio era una sola URL casi sin texto. Estas rutas
devuelven el contenido en el HTML crudo, en inglés. Solo se indexan los ítems POTENCIAL y
POTENCIAL_SIN_ORDENES: miles de ítems casi idénticos serían contenido fino.
"""
import html
import json
import re
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend.api.deps import _db
from backend.api.seo import CANONICAL_HOST

router = APIRouter()

BASE_URL = f"https://{CANONICAL_HOST}"
INDEXABLE_STATUSES = ("POTENCIAL", "POTENCIAL_SIN_ORDENES")
_STATUS_PLACEHOLDERS = ",".join("?" * len(INDEXABLE_STATUSES))
SITEMAP_LANGS = ("en", "es", "de", "fr", "it")
PAGE_CACHE = "public, max-age=3600"
HUB_LIMIT = 2000
RELATED_LIMIT = 8

STATUS_EN = {
    "POTENCIAL": "Potential",
    "POTENCIAL_SIN_ORDENES": "No orders",
    "EN_OBSERVACION": "Under observation",
    "DESCARTADO": "Discarded",
}
STATUS_BLURB = {
    "POTENCIAL": "its spread, liquidity and real market activity over the last 7 days meet the criteria.",
    "POTENCIAL_SIN_ORDENES": (
        "its spread and liquidity qualify, but the executed-trade history is too low "
        "(little volume or few trades per day)."
    ),
    "EN_OBSERVACION": "it is a borderline case and needs more history.",
    "DESCARTADO": "its spread is losing or its liquidity is unviable.",
}
# The engines store these labels in Spanish; they are shown here in English.
SPREAD_EN = {
    "❌ Pérdida": "Loss",
    "🟡 Casi cero": "Near zero",
    "🟢 Pequeño beneficio": "Small profit",
    "🟢 Buen margen": "Good margin",
    "🟢🟢 Muy bueno": "Very good",
    "🟢🟢🟢 Excelente, si existe volumen": "Excellent, if volume exists",
}
LIQUIDITY_EN = {
    "Excelente liquidez": "Excellent liquidity",
    "Buena": "Good",
    "Aceptable": "Acceptable",
    "Cuidado": "Careful",
    "Muy lenta para tu capital": "Too slow for your capital",
}

_CSS = (
    "body{margin:0;background:#08090f;color:#e7eaf3;font:16px/1.55 system-ui,sans-serif}"
    "main{max-width:860px;margin:0 auto;padding:24px 16px}a{color:#3fd0ff}"
    "nav a{margin-right:16px}table{border-collapse:collapse;width:100%;margin:16px 0}"
    "th,td{border-bottom:1px solid rgba(255,255,255,.12);padding:8px;text-align:left}"
    "th{color:rgba(231,234,243,.65);font-weight:600;width:48%}small,.muted{color:rgba(231,234,243,.6)}"
    "ul{padding-left:20px}.pos{color:#3ddc84}.neg{color:#ff8a8a}"
)


def lang_path(lang: str) -> str:
    """URL path of the home page in a language: English lives at the root."""
    return "/" if lang == "en" else f"/{lang}/"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


def item_path(type_id: int, name: str) -> str:
    return f"/items/{type_id}-{slugify(name)}"


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _isk(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f} ISK"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _json_ld(name: str, path: str, crumbs: list[tuple[str, str]], about: str | None) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": name,
        "url": f"{BASE_URL}{path}",
        "inLanguage": "en",
        "isPartOf": {"@type": "WebSite", "name": "EveMarket Screener", "url": f"{BASE_URL}/"},
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": label, "item": f"{BASE_URL}{href}"}
                for i, (label, href) in enumerate(crumbs)
            ],
        },
    }
    if about:
        data["about"] = {"@type": "Thing", "name": about}
    # `</` (or `<!--`) inside a <script> would end it early; the names come from the ESI, so
    # escape every <, > and & as JSON unicode escapes (same text for a JSON parser).
    payload = json.dumps(data, ensure_ascii=False)
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        payload = payload.replace(char, escaped)
    return f'<script type="application/ld+json">{payload}</script>\n'


def _page(title: str, description: str, canonical_path: str, body: str, robots: str,
          json_ld: str = "") -> str:
    canonical = f"{BASE_URL}{canonical_path}"
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        f'<meta name="description" content="{_e(description)}">\n'
        f'<meta name="robots" content="{_e(robots)}">\n'
        f'<link rel="canonical" href="{_e(canonical)}">\n'
        '<meta property="og:type" content="website">\n'
        '<meta property="og:site_name" content="EveMarket Screener">\n'
        f'<meta property="og:title" content="{_e(title)}">\n'
        f'<meta property="og:description" content="{_e(description)}">\n'
        f'<meta property="og:url" content="{_e(canonical)}">\n'
        f'<meta property="og:image" content="{BASE_URL}/icon-512.png">\n'
        '<meta name="twitter:card" content="summary">\n'
        '<link rel="icon" type="image/png" href="/icon-192.png">\n'
        f"<style>{_CSS}</style>\n{json_ld}</head>\n<body><main>\n"
        '<nav><a href="/">Screener</a><a href="/items">All items</a></nav>\n'
        f"{body}\n"
        "<p><small>Independent site, not affiliated with CCP Games. EVE Online is a trademark of "
        "CCP hf. Informational tool, not investment advice. Data from the official ESI API."
        "</small></p>\n</main></body></html>\n"
    )


def _html(content: str) -> HTMLResponse:
    return HTMLResponse(content, headers={"Cache-Control": PAGE_CACHE})


def _not_found() -> HTMLResponse:
    body = '<h1>Item not found</h1><p>This item is not tracked. See <a href="/items">all items</a>.</p>'
    page = _page("Item not found | EveMarket Screener", "Item not found.", "/items", body, "noindex")
    return HTMLResponse(page, status_code=404, headers={"Cache-Control": "no-cache"})


@router.get("/items", response_class=HTMLResponse, include_in_schema=False)
def items_index() -> HTMLResponse:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT s.type_id, i.name, s.status, s.roi, "
            "COALESCE(c.category_name, 'Other') AS category "
            "FROM item_status s JOIN item_type i ON i.type_id = s.type_id "
            "LEFT JOIN item_category c ON c.type_id = s.type_id "
            f"WHERE s.status IN ({_STATUS_PLACEHOLDERS}) "
            "ORDER BY s.volumen_diario_real DESC LIMIT ?",
            (*INDEXABLE_STATUSES, HUB_LIMIT),
        ).fetchall()
    finally:
        conn.close()

    by_category: dict[str, list] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    sections = []
    for category in sorted(by_category):
        links = "".join(
            f'<li><a href="{_e(item_path(r["type_id"], r["name"]))}">{_e(r["name"])}</a> '
            f'<span class="muted">ROI {_pct(r["roi"])}</span></li>'
            for r in by_category[category]
        )
        sections.append(f"<h2>{_e(category)} ({len(by_category[category])})</h2><ul>{links}</ul>")

    body = (
        "<h1>EVE Online station trading: items worth trading in Jita</h1>"
        f"<p>{len(rows)} items in The Forge (Jita) whose spread, liquidity and recent trade "
        "history make them candidates for station trading, ranked by daily volume within each "
        "category. Refreshed every 4 hours from the official ESI API. For live filters and "
        'sorting use the <a href="/">interactive Screener</a>.</p>' + "".join(sections)
    )
    title = "EVE Online station trading items in Jita | EveMarket Screener"
    description = (
        f"{len(rows)} EVE Online items worth station trading in Jita, with ROI, spread and "
        "liquidity, refreshed every 4 hours."
    )
    ld = _json_ld(title, "/items", [("Screener", "/"), ("All items", "/items")], None)
    return _html(_page(title, description, "/items", body, "index, follow", ld))


@router.get("/items/{item_ref}", response_class=HTMLResponse, include_in_schema=False)
def item_page(item_ref: str):
    match = re.match(r"^(\d+)(?:-.*)?$", item_ref)
    if not match:
        return _not_found()
    type_id = int(match.group(1))

    conn = _db()
    try:
        row = conn.execute(
            "SELECT s.*, i.name, c.category_id, c.category_name, c.group_name "
            "FROM item_status s JOIN item_type i ON i.type_id = s.type_id "
            "LEFT JOIN item_category c ON c.type_id = s.type_id WHERE s.type_id = ?",
            (type_id,),
        ).fetchone()
        if row is None:
            return _not_found()
        snapshot = conn.execute(
            "SELECT buy_order_count, sell_order_count FROM market_snapshot WHERE type_id = ? "
            "ORDER BY captured_at DESC LIMIT 1", (type_id,),
        ).fetchone()
        related = []
        if row["category_id"] is not None:
            related = conn.execute(
                "SELECT s.type_id, i.name FROM item_status s "
                "JOIN item_type i ON i.type_id = s.type_id "
                "JOIN item_category c ON c.type_id = s.type_id "
                "WHERE c.category_id = ? AND s.type_id != ? "
                f"AND s.status IN ({_STATUS_PLACEHOLDERS}) "
                "ORDER BY s.volumen_diario_real DESC LIMIT ?",
                (row["category_id"], type_id, *INDEXABLE_STATUSES, RELATED_LIMIT),
            ).fetchall()
    finally:
        conn.close()

    canonical_path = item_path(type_id, row["name"])
    if f"/items/{item_ref}" != canonical_path:
        return RedirectResponse(canonical_path, status_code=301)

    name = row["name"]
    status = row["status"]
    status_label = STATUS_EN.get(status, status)
    spread_label = SPREAD_EN.get(row["evaluacion_spread"], row["evaluacion_spread"])
    liquidity_label = LIQUIDITY_EN.get(row["liquidez"], row["liquidez"])
    roi_class = "pos" if (row["roi"] or 0) >= 0 else "neg"
    evaluated = row["last_evaluated_at"] or ""
    volume = row["avg_daily_volume_7d"]
    trades = row["avg_daily_order_count_7d"]

    # Each value is already HTML-safe: plain text goes through _e(), markup is literal.
    facts = [
        ("Classification", _e(status_label)),
        ("Best buy price", _e(_isk(row["best_buy"]))),
        ("Best sell price", _e(_isk(row["best_sell"]))),
        ("ROI", f'<span class="{roi_class}">{_e(_pct(row["roi"]))}</span>'),
        ("Gross spread", _e(_pct(row["spread_bruto"]))),
        ("Spread rating", _e(spread_label)),
        ("Liquidity", _e(liquidity_label)),
        ("Average daily volume (7 days)", _e(f"{volume:,.0f} units" if volume is not None else "—")),
        ("Trades per day (7 days)", _e(f"{trades:.1f}" if trades is not None else "—")),
    ]
    if snapshot:
        facts += [
            ("Active buy orders", _e(f"{snapshot['buy_order_count']:,}")),
            ("Active sell orders", _e(f"{snapshot['sell_order_count']:,}")),
        ]
    table = "".join(f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in facts)

    category_line = ""
    if row["category_name"]:
        group = f" · Group: {_e(row['group_name'])}" if row["group_name"] else ""
        category_line = f'<p class="muted">Category: {_e(row["category_name"])}{group}</p>'
    related_html = ""
    if related:
        links = "".join(
            f'<li><a href="{_e(item_path(r["type_id"], r["name"]))}">{_e(r["name"])}</a></li>'
            for r in related
        )
        related_html = f"<h2>More {_e(row['category_name'])} items</h2><ul>{links}</ul>"
    evaluated_html = ""
    if evaluated:
        shown = evaluated[:16].replace("T", " ")
        evaluated_html = (
            f'<p class="muted">Last evaluated <time datetime="{_e(evaluated)}">{_e(shown)} UTC</time>. '
            "The market engine refreshes every 4 hours.</p>"
        )

    summary = (
        f"{_e(name)} is currently classified as <strong>{_e(status_label)}</strong> for station "
        f"trading in The Forge (Jita): {_e(STATUS_BLURB.get(status, ''))} The best buy order is "
        f"{_e(_isk(row['best_buy']))} and the best sell order is {_e(_isk(row['best_sell']))}."
    )
    body = (
        f"<h1>{_e(name)} — station trading in Jita</h1><p>{summary}</p>{category_line}"
        f"<table>{table}</table>{evaluated_html}"
        '<p>Want to filter and compare every item? Open the <a href="/">interactive Screener</a>.</p>'
        f"{related_html}"
    )
    title = _trim(f"{name}: Jita station trading, ROI {_pct(row['roi'])}", 56) + " | EveMarket"
    description = _trim(
        f"{name} in EVE Online: {status_label} for station trading in Jita. Buy "
        f"{_isk(row['best_buy'])}, sell {_isk(row['best_sell'])}, ROI {_pct(row['roi'])}, "
        f"{liquidity_label.lower()}.", 158,
    )
    ld = _json_ld(
        f"{name} — station trading in Jita", canonical_path,
        [("Screener", "/"), ("All items", "/items"), (name, canonical_path)], name,
    )
    robots = "index, follow" if status in INDEXABLE_STATUSES else "noindex, follow"
    return _html(_page(title, description, canonical_path, body, robots, ld))


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> Response:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT s.type_id, i.name, s.last_evaluated_at FROM item_status s "
            "JOIN item_type i ON i.type_id = s.type_id "
            f"WHERE s.status IN ({_STATUS_PLACEHOLDERS}) ORDER BY s.type_id",
            INDEXABLE_STATUSES,
        ).fetchall()
        latest = conn.execute("SELECT MAX(last_evaluated_at) FROM item_status").fetchone()[0]
    finally:
        conn.close()

    def lastmod(value: str | None) -> str:
        try:
            return datetime.fromisoformat(value).date().isoformat() if value else ""
        except ValueError:
            return ""

    def url(loc: str, mod: str, alternates: str = "") -> str:
        tag = f"<lastmod>{mod}</lastmod>" if mod else ""
        return f"<url><loc>{_e(loc)}</loc>{tag}{alternates}<changefreq>daily</changefreq></url>"

    # Same alternates as the <link rel="alternate"> tags of the per-language pages (the
    # frontend build generates /es/, /de/, /fr/, /it/): every language URL lists the full set.
    home_alternates = "".join(
        f'<xhtml:link rel="alternate" hreflang="{lang}" href="{BASE_URL}{lang_path(lang)}"/>'
        for lang in SITEMAP_LANGS
    ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{BASE_URL}/"/>'
    parts = [
        url(f"{BASE_URL}{lang_path(lang)}", lastmod(latest), home_alternates)
        for lang in SITEMAP_LANGS
    ]
    parts.append(url(f"{BASE_URL}/items", lastmod(latest)))
    parts += [
        url(f"{BASE_URL}{item_path(r['type_id'], r['name'])}", lastmod(r["last_evaluated_at"]))
        for r in rows
    ]
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(parts) + "\n</urlset>\n"
    )
    return Response(xml, media_type="application/xml", headers={"Cache-Control": PAGE_CACHE})
