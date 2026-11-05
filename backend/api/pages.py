"""Páginas HTML públicas generadas en el servidor (SEO): una por ítem
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

# Look and feel shared with the React app (same tokens as frontend/app/src/App.css). The
# fonts are the same files the SPA bundles, copied to frontend/app/public/fonts. Inline
# styles are allowed by the CSP; inline scripts are not, so the item filter lives in
# /items-filter.js.
_CSS = r"""
@font-face{font-family:'Space Grotesk';font-weight:500;font-display:swap;src:url(/fonts/space-grotesk-latin-500-normal.woff2) format('woff2')}
@font-face{font-family:'Space Grotesk';font-weight:600;font-display:swap;src:url(/fonts/space-grotesk-latin-600-normal.woff2) format('woff2')}
@font-face{font-family:'Space Grotesk';font-weight:700;font-display:swap;src:url(/fonts/space-grotesk-latin-700-normal.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Mono';font-weight:400;font-display:swap;src:url(/fonts/ibm-plex-mono-latin-400-normal.woff2) format('woff2')}
@font-face{font-family:'IBM Plex Mono';font-weight:500;font-display:swap;src:url(/fonts/ibm-plex-mono-latin-500-normal.woff2) format('woff2')}
:root{--ink:#e7eaf3;--dim:rgba(231,234,243,.6);--faint:rgba(231,234,243,.38);--line:rgba(255,255,255,.08);--panel:rgba(255,255,255,.045);--cyan:#3fd0ff;--purple:#7c6cf7;--pos:#3ddc84;--pos-soft:rgba(61,220,132,.14);--neg:#ff8a8a;--neg-soft:rgba(255,93,93,.12);--sans:'Space Grotesk',system-ui,sans-serif;--mono:'IBM Plex Mono',ui-monospace,monospace}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{scroll-behavior:smooth;scroll-padding-top:76px}
body{margin:0;min-height:100svh;color:var(--ink);font:16px/1.55 var(--sans);background:linear-gradient(180deg,#0d1020 0%,#0a0c14 55%,#08090f 100%) fixed}
body::before,body::after{content:"";position:fixed;border-radius:50%;filter:blur(90px);pointer-events:none;z-index:-1}
body::before{width:340px;height:340px;top:-120px;right:-100px;background:var(--cyan);opacity:.16}
body::after{width:300px;height:300px;bottom:60px;left:-100px;background:var(--purple);opacity:.13}
a{color:var(--cyan)}
.top{position:sticky;top:0;z-index:30;background:rgba(9,11,18,.78);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}
.top-in{max-width:1100px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:20px}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:1rem;letter-spacing:-.2px;text-decoration:none;white-space:nowrap}
.brand img{width:24px;height:24px;border-radius:6px}
.brand b{background:linear-gradient(90deg,var(--ink) 0%,var(--cyan) 140%);-webkit-background-clip:text;background-clip:text;color:transparent}
.top-links{display:flex;gap:20px;flex:1}
.top-links a{color:var(--dim);font-size:.9rem;font-weight:500;text-decoration:none}
.top-links a:hover,.top-links a[aria-current]{color:var(--ink)}
.cta{padding:8px 14px;border-radius:9px;background:var(--cyan);color:#04141c;font-size:.8rem;font-weight:700;text-decoration:none;white-space:nowrap}
.cta:hover{background:#8fe3ff}
main{max-width:1100px;margin:0 auto;padding:28px 16px 8px}
h1{margin:0 0 10px;font-size:clamp(1.6rem,4.2vw,2.4rem);line-height:1.15;letter-spacing:-.5px}
h2{margin:0;font-size:1.1rem;font-weight:700}
.lede{margin:0 0 18px;max-width:68ch;color:var(--dim)}
.muted,small{color:var(--dim)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 22px;padding:0;list-style:none}
.chips li{padding:5px 12px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--dim);font-size:.8rem}
.chips b{color:var(--ink);font-family:var(--mono);font-weight:500}
.tools{display:grid;gap:12px;margin:0 0 26px}
.search{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);font:inherit;font-size:.95rem}
.search::placeholder{color:var(--faint)}
.search:focus{outline:none;border-color:rgba(63,208,255,.55)}
.jump{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.jump a{display:block;padding:4px 10px;border:1px solid var(--line);border-radius:999px;color:var(--dim);font-size:.78rem;text-decoration:none}
.jump a:hover{color:var(--ink);border-color:rgba(63,208,255,.45)}
.cat{margin:0 0 28px}
.cat-head{display:flex;align-items:baseline;gap:10px;margin:0 0 12px}
.count{padding:1px 9px;border-radius:999px;background:var(--panel);border:1px solid var(--line);color:var(--dim);font-family:var(--mono);font-size:.74rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin:0;padding:0;list-style:none}
.card{display:flex;align-items:center;justify-content:space-between;gap:10px;height:100%;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);font-size:.88rem;font-weight:600;line-height:1.25;text-decoration:none;overflow-wrap:anywhere}
.card:hover{border-color:rgba(63,208,255,.45)}
.roi{flex:0 0 auto;padding:2px 8px;border-radius:999px;background:var(--pos-soft);color:var(--pos);font-family:var(--mono);font-size:.76rem;font-weight:500;white-space:nowrap}
.roi.neg{background:var(--neg-soft);color:var(--neg)}
.empty{padding:28px 0;color:var(--dim);text-align:center}
.crumbs{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px;color:var(--faint);font-size:.82rem}
.crumbs a{color:var(--dim);text-decoration:none}
.crumbs a:hover{color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:18px 0}
.kpi{padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
.kpi span{display:block;color:var(--dim);font-size:.74rem}
.kpi strong{display:block;margin-top:4px;font-family:var(--mono);font-size:1.15rem;font-weight:500;overflow-wrap:anywhere}
table{width:100%;margin:16px 0;border-collapse:separate;border-spacing:0;border:1px solid var(--line);border-radius:14px;background:var(--panel);overflow:hidden}
th,td{padding:11px 16px;border-bottom:1px solid var(--line);text-align:left}
tr:last-child th,tr:last-child td{border-bottom:0}
th{width:48%;color:var(--dim);font-weight:500;font-size:.9rem}
td{font-family:var(--mono);font-size:.9rem}
.pos{color:var(--pos)}.neg{color:var(--neg)}
ul{padding-left:20px}
.site-foot{max-width:1100px;margin:32px auto 0;padding:18px 16px 32px;border-top:1px solid var(--line);color:var(--dim);font-size:.8rem}
.site-foot p{margin:0 0 12px;max-width:64ch;line-height:1.5}
.site-foot nav{display:flex;flex-wrap:wrap;gap:8px 18px}
.site-foot a{color:var(--dim)}
.site-foot a:hover{color:var(--ink)}
@media (max-width:640px){.top-in{gap:12px}.top-links{gap:14px}.cta{display:none}.kpis{grid-template-columns:1fr}.grid{grid-template-columns:1fr}th,td{padding:10px 12px}th{width:46%}}
"""


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
          json_ld: str = "", scripts: str = "") -> str:
    canonical = f"{BASE_URL}{canonical_path}"
    items_current = ' aria-current="page"' if canonical_path == "/items" else ""
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
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n'
        '<link rel="icon" type="image/png" href="/icon-192.png">\n'
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
        '<meta name="theme-color" content="#08090f">\n'
        '<link rel="preload" href="/fonts/space-grotesk-latin-600-normal.woff2" as="font" '
        'type="font/woff2" crossorigin>\n'
        f"<style>{_CSS}</style>\n{json_ld}</head>\n<body>\n"
        '<header class="top"><div class="top-in">'
        '<a class="brand" href="/"><img src="/icon-192.png" alt="" width="24" height="24">'
        "<b>EveMarket</b></a>"
        '<nav class="top-links" aria-label="Main"><a href="/">Screener</a>'
        f'<a href="/items"{items_current}>All items</a></nav>'
        '<a class="cta" href="/">Open the Screener</a></div></header>\n'
        f"<main>\n{body}\n</main>\n"
        '<footer class="site-foot"><p>Independent site, not affiliated with CCP Games. EVE Online '
        "is a trademark of CCP hf. Informational tool, not investment advice. Data from the "
        "official ESI API.</p>"
        '<nav aria-label="Footer"><a href="/">Screener</a><a href="/items">All items</a>'
        '<a href="/privacy">Privacy</a></nav>'
        f'</footer>\n{scripts}<script src="/analytics.js" defer></script>\n</body></html>\n'
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
    jump = []
    for category in sorted(by_category):
        anchor = f"cat-{slugify(category)}"
        cards = "".join(
            f'<li><a class="card" data-n="{_e(r["name"].lower())}" '
            f'href="{_e(item_path(r["type_id"], r["name"]))}"><span>{_e(r["name"])}</span>'
            f'<span class="roi{"" if (r["roi"] or 0) >= 0 else " neg"}">{_pct(r["roi"])}</span></a></li>'
            for r in by_category[category]
        )
        count = len(by_category[category])
        jump.append(f'<li><a href="#{anchor}">{_e(category)} · {count}</a></li>')
        sections.append(
            f'<section class="cat" id="{anchor}"><div class="cat-head"><h2>{_e(category)}</h2>'
            f'<span class="count">{count}</span></div><ul class="grid">{cards}</ul></section>'
        )

    body = (
        "<h1>EVE Online station trading: items worth trading in Jita</h1>"
        f"<p class=\"lede\">{len(rows):,} items in The Forge (Jita) whose spread, liquidity and "
        "recent trade history make them candidates for station trading, ranked by daily volume "
        "within each category. Refreshed every 4 hours from the official ESI API. For live "
        'filters and sorting use the <a href="/">interactive Screener</a>.</p>'
        f'<ul class="chips"><li><b>{len(rows):,}</b> items</li>'
        f'<li><b>{len(by_category)}</b> categories</li><li>Updated every <b>4 h</b></li>'
        "<li>ROI after fees</li></ul>"
        '<div class="tools"><input class="search" id="q" type="search" hidden '
        'placeholder="Search an item, e.g. Tritanium or Insignia" aria-label="Search items" '
        f'autocomplete="off"><ul class="jump" aria-label="Categories">{"".join(jump)}</ul></div>'
        + "".join(sections)
        + '<p class="empty" id="empty" hidden>No items match your search.</p>'
    )
    title = "EVE Online station trading items in Jita | EveMarket Screener"
    description = (
        f"{len(rows)} EVE Online items worth station trading in Jita, with ROI, spread and "
        "liquidity, refreshed every 4 hours."
    )
    ld = _json_ld(title, "/items", [("Screener", "/"), ("All items", "/items")], None)
    return _html(_page(title, description, "/items", body, "index, follow", ld,
                       '<script src="/items-filter.js" defer></script>\n'))


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
            f'<li><a class="card" href="{_e(item_path(r["type_id"], r["name"]))}">'
            f'<span>{_e(r["name"])}</span></a></li>'
            for r in related
        )
        related_html = (
            f'<div class="cat-head" style="margin-top:28px"><h2>More {_e(row["category_name"])} '
            f'items</h2></div><ul class="grid">{links}</ul>'
        )
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
    crumbs = (
        '<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Screener</a><span>/</span>'
        f'<a href="/items">All items</a><span>/</span><span>{_e(name)}</span></nav>'
    )
    kpis = (
        '<div class="kpis">'
        f'<div class="kpi"><span>ROI</span><strong class="{roi_class}">{_e(_pct(row["roi"]))}</strong></div>'
        f'<div class="kpi"><span>Buy → sell</span><strong>{_e(_isk(row["best_buy"]))} → '
        f'{_e(_isk(row["best_sell"]))}</strong></div>'
        f'<div class="kpi"><span>Trades per day (7d)</span>'
        f'<strong>{_e(f"{trades:.1f}" if trades is not None else "—")}</strong></div></div>'
    )
    body = (
        f"{crumbs}<h1>{_e(name)} — station trading in Jita</h1><p class=\"lede\">{summary}</p>"
        f"{category_line}{kpis}<table>{table}</table>{evaluated_html}"
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


_PRIVACY = {
    "en": ("Privacy", [
        "This site is an independent EVE Online tool. It works without accounts and the Screener data is public.",
        "<b>Usage metrics (only if you accept the banner).</b> We save a random ID in your browser (localStorage) and, on our server, "
        "the dates and times of your visits, the pages you open, how many seconds the page is visible, your language and the host of the "
        "site that sent you here. We do not store your IP address or browser details, we do not use it for advertising and we do not "
        "share it. Purpose: to know how many people use the site and whether they come back.",
        "<b>Retention.</b> 13 months, then it is deleted automatically.",
        "<b>Your choice.</b> Rejecting, or withdrawing later with the button below, deletes the ID from your browser and your records "
        "from our server. Browsers that send Global Privacy Control or Do Not Track are treated as a rejection.",
        "<b>Hosting.</b> The site is served through Cloudflare, which processes network requests for us and runs its own cookie-free "
        "traffic statistics.",
        "<button type=\"button\" data-eve-consent-settings>Change my choice</button>",
    ]),
    "es": ("Privacidad", [
        "Este sitio es una herramienta independiente para EVE Online. Funciona sin cuentas y los datos del Screener son públicos.",
        "<b>Métricas de uso (solo si aceptas el aviso).</b> Guardamos un ID aleatorio en tu navegador (localStorage) y, en nuestro "
        "servidor, las fechas de tus visitas, las páginas que abres, los segundos que la página está visible, tu idioma y el sitio "
        "desde el que llegaste. No guardamos tu IP ni datos de tu navegador, no lo usamos para publicidad y no lo compartimos. "
        "Finalidad: saber cuánta gente usa el sitio y si vuelve.",
        "<b>Conservación.</b> 13 meses; después se borra solo.",
        "<b>Tu decisión.</b> Si rechazas, o retiras el permiso después con el botón de abajo, se borra el ID de tu navegador y tus "
        "registros del servidor. Los navegadores que envían Global Privacy Control o No Rastrear se tratan como un rechazo.",
        "<b>Alojamiento.</b> El sitio se sirve a través de Cloudflare, que procesa las peticiones de red por nuestra cuenta y ofrece "
        "sus propias estadísticas sin cookies.",
        "<button type=\"button\" data-eve-consent-settings>Cambiar mi decisión</button>",
    ]),
    "de": ("Datenschutz", [
        "Diese Seite ist ein unabhängiges Werkzeug für EVE Online. Sie funktioniert ohne Konto, die Daten des Screeners sind öffentlich.",
        "<b>Nutzungsstatistik (nur wenn du das Banner akzeptierst).</b> Wir speichern eine zufällige ID in deinem Browser "
        "(localStorage) und auf unserem Server Datum und Uhrzeit deiner Besuche, die geöffneten Seiten, die Sekunden, in denen die "
        "Seite sichtbar ist, deine Sprache und die Herkunftsseite. Deine IP-Adresse und Browserdaten speichern wir nicht, wir "
        "nutzen sie nicht für Werbung und geben sie nicht weiter. Zweck: wissen, wie viele Menschen die Seite nutzen und ob sie wiederkommen.",
        "<b>Speicherdauer.</b> 13 Monate, danach wird alles automatisch gelöscht.",
        "<b>Deine Wahl.</b> Bei Ablehnung oder späterem Widerruf über die Schaltfläche unten werden die ID im Browser und deine "
        "Einträge auf unserem Server gelöscht. Browser mit Global Privacy Control oder Do Not Track gelten als Ablehnung.",
        "<b>Hosting.</b> Die Seite wird über Cloudflare ausgeliefert, das Netzwerkanfragen in unserem Auftrag verarbeitet und eigene "
        "cookiefreie Statistiken erhebt.",
        "<button type=\"button\" data-eve-consent-settings>Meine Wahl ändern</button>",
    ]),
    "fr": ("Confidentialité", [
        "Ce site est un outil indépendant pour EVE Online. Il fonctionne sans compte et les données du Screener sont publiques.",
        "<b>Mesure d'audience (uniquement si vous acceptez le bandeau).</b> Nous enregistrons un identifiant aléatoire dans votre "
        "navigateur (localStorage) et, sur notre serveur, les dates de vos visites, les pages ouvertes, les secondes pendant lesquelles "
        "la page est visible, votre langue et le site d'origine. Nous ne conservons ni votre adresse IP ni les détails de votre "
        "navigateur, nous ne l'utilisons pas pour la publicité et nous ne le partageons pas. Finalité : savoir combien de personnes "
        "utilisent le site et si elles reviennent.",
        "<b>Conservation.</b> 13 mois, puis suppression automatique.",
        "<b>Votre choix.</b> En refusant, ou en retirant votre accord avec le bouton ci-dessous, l'identifiant de votre navigateur et "
        "vos enregistrements sur notre serveur sont supprimés. Les navigateurs qui envoient Global Privacy Control ou Do Not Track "
        "sont traités comme un refus.",
        "<b>Hébergement.</b> Le site est servi par Cloudflare, qui traite les requêtes réseau pour notre compte et propose ses propres "
        "statistiques sans cookies.",
        "<button type=\"button\" data-eve-consent-settings>Modifier mon choix</button>",
    ]),
    "it": ("Privacy", [
        "Questo sito è uno strumento indipendente per EVE Online. Funziona senza account e i dati dello Screener sono pubblici.",
        "<b>Statistiche d'uso (solo se accetti il banner).</b> Salviamo un ID casuale nel tuo browser (localStorage) e, sul nostro "
        "server, le date delle visite, le pagine aperte, i secondi in cui la pagina è visibile, la lingua e il sito di provenienza. "
        "Non conserviamo il tuo indirizzo IP né dati del browser, non lo usiamo per la pubblicità e non lo condividiamo. Scopo: "
        "sapere quante persone usano il sito e se tornano.",
        "<b>Conservazione.</b> 13 mesi, poi viene cancellato automaticamente.",
        "<b>La tua scelta.</b> Se rifiuti, o revochi dopo con il pulsante qui sotto, l'ID nel browser e i tuoi dati sul nostro server "
        "vengono cancellati. I browser che inviano Global Privacy Control o Do Not Track sono trattati come un rifiuto.",
        "<b>Hosting.</b> Il sito è servito tramite Cloudflare, che elabora le richieste di rete per nostro conto e offre statistiche "
        "proprie senza cookie.",
        "<button type=\"button\" data-eve-consent-settings>Cambia la mia scelta</button>",
    ]),
}
_PRIVACY_LANG_NAMES = {"en": "English", "es": "Español", "de": "Deutsch", "fr": "Français", "it": "Italiano"}


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
def privacy_page():
    sections = "".join(
        f'<section lang="{code}"><h2>{_e(title)} <small>({_PRIVACY_LANG_NAMES[code]})</small></h2>'
        + "".join(f"<p>{para}</p>" for para in paragraphs) + "</section>"
        for code, (title, paragraphs) in _PRIVACY.items()
    )
    body = f"<h1>Privacy / Privacidad</h1>\n{sections}"
    return _html(_page(
        "Privacy | EveMarket Screener", "How EveMarket Screener handles usage data and your consent.",
        "/privacy", body, "noindex,follow",
    ))


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
