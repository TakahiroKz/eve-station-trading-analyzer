"""Portadas públicas por mercado (SEO): `/amarr/`, `/es/amarr/`, ... una por mercado activo e idioma.

La PWA elige el mercado con `?market=` (una vista de la SPA que los buscadores no tratan como una
página). Estas rutas dan a cada hub una URL propia, con contenido real en el HTML crudo: cifras
del mercado (ítems por estado, hora de actualización) y los 10 ítems más operados entre los
candidatos. Mismo criterio que `pages.py`: solo cuentan los estados indexables, y un mercado sin
candidatos o con datos viejos se sirve `noindex` para no publicar contenido vacío o desactualizado.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.api.deps import _db
from backend.api.pages import (
    _STATUS_PLACEHOLDERS, BASE_URL, CHROME_EN, INDEXABLE_STATUSES, SITEMAP_LANGS, _e, _html,
    _isk, _json_ld, _not_found, _page, _pct, item_path, lang_path,
)
from storage.db import DEFAULT_MARKET, MARKETS_SEED

router = APIRouter()

MARKET_SLUGS = tuple(seed[0] for seed in MARKETS_SEED)
REGION_NAMES = {
    "jita": "The Forge", "amarr": "Domain", "dodixie": "Sinq Laison", "rens": "Heimatar", "hek": "Metropolis",
}
TOP_LIMIT = 10
MAX_AGE = timedelta(hours=1)  # más viejo que esto, la portada del mercado no se indexa

# Textos por idioma. Los marcadores {market}, {region} y {n} se rellenan en `_texts`.
T = {
    "en": {
        "title": "{market} station trading in EVE Online: best items by ROI | EveMarket Screener",
        "desc": "Which items are worth station trading in {market} ({region}): {n} candidates ranked by ROI, spread and liquidity, refreshed every 5 minutes.",
        "h1": "Station trading in {market}: items worth trading",
        "lede": "{n} items in {market} ({region}) whose spread, liquidity and recent trade history make them candidates for station trading. Prices and calculations refresh every 5 minutes from the official ESI API.",
        "k_potential": "candidates", "k_tracked": "items tracked", "k_updated": "last update",
        "top": "The {limit} most traded candidates in {market}",
        "note": "Ranked by trades per day over the last 7 days. ROI is calculated after fees.",
        "item": "Item", "roi": "ROI", "buy": "Best buy", "sell": "Best sell", "trades": "Trades/day",
        "open": "Open the live {market} screener with filters and sorting",
        "hubs": "Other trade hubs", "crumb": "Screener",
        "chrome": CHROME_EN,
    },
    "es": {
        "title": "Station trading en {market} (EVE Online): mejores ítems por ROI | EveMarket Screener",
        "desc": "Qué ítems conviene comerciar en {market} ({region}): {n} candidatos ordenados por ROI, spread y liquidez, actualizado cada 5 minutos.",
        "h1": "Station trading en {market}: ítems que conviene comerciar",
        "lede": "{n} ítems en {market} ({region}) cuyo spread, liquidez e historial reciente de operaciones los hacen candidatos para el station trading. Precios y cálculos se actualizan cada 5 minutos desde la API oficial ESI.",
        "k_potential": "candidatos", "k_tracked": "ítems analizados", "k_updated": "última actualización",
        "top": "Los {limit} candidatos más operados en {market}",
        "note": "Ordenados por operaciones al día en los últimos 7 días. El ROI se calcula después de comisiones.",
        "item": "Ítem", "roi": "ROI", "buy": "Mejor compra", "sell": "Mejor venta", "trades": "Operaciones/día",
        "open": "Abrir el screener de {market} en vivo, con filtros y orden",
        "hubs": "Otros mercados", "crumb": "Screener",
        "chrome": {
            "screener": "Screener", "items": "Todos los ítems (EN)", "cta": "Abrir el Screener",
            "disclaimer": (
                "Sitio independiente, sin afiliación con CCP Games. EVE Online es una marca de CCP hf. "
                "Herramienta informativa, no es asesoramiento de inversión. Datos de la API oficial ESI."
            ),
            "privacy": "Privacidad",
        },
    },
    "de": {
        "title": "Station Trading in {market} (EVE Online): beste Items nach ROI | EveMarket Screener",
        "desc": "Welche Items sich in {market} ({region}) zu handeln lohnen: {n} Kandidaten nach ROI, Spread und Liquidität, alle 5 Minuten aktualisiert.",
        "h1": "Station Trading in {market}: Items, die sich lohnen",
        "lede": "{n} Items in {market} ({region}), deren Spread, Liquidität und jüngster Handelsverlauf sie zu Kandidaten für Station Trading machen. Preise und Berechnungen werden alle 5 Minuten aus der offiziellen ESI-API aktualisiert.",
        "k_potential": "Kandidaten", "k_tracked": "analysierte Items", "k_updated": "letzte Aktualisierung",
        "top": "Die {limit} meistgehandelten Kandidaten in {market}",
        "note": "Sortiert nach Trades pro Tag in den letzten 7 Tagen. Der ROI ist nach Gebühren berechnet.",
        "item": "Item", "roi": "ROI", "buy": "Bester Kauf", "sell": "Bester Verkauf", "trades": "Trades/Tag",
        "open": "Den Live-Screener für {market} mit Filtern und Sortierung öffnen",
        "hubs": "Weitere Handelszentren", "crumb": "Screener",
        "chrome": {
            "screener": "Screener", "items": "Alle Items (EN)", "cta": "Screener öffnen",
            "disclaimer": (
                "Unabhängige Seite, nicht mit CCP Games verbunden. EVE Online ist eine Marke von CCP hf. "
                "Informationswerkzeug, keine Anlageberatung. Daten aus der offiziellen ESI-API."
            ),
            "privacy": "Datenschutz",
        },
    },
    "fr": {
        "title": "Station trading à {market} (EVE Online) : meilleurs objets par ROI | EveMarket Screener",
        "desc": "Quels objets valent la peine d'être échangés à {market} ({region}) : {n} candidats classés par ROI, spread et liquidité, actualisé toutes les 5 minutes.",
        "h1": "Station trading à {market} : les objets qui valent le coup",
        "lede": "{n} objets à {market} ({region}) dont le spread, la liquidité et l'historique récent des échanges en font des candidats au station trading. Prix et calculs actualisés toutes les 5 minutes depuis l'API officielle ESI.",
        "k_potential": "candidats", "k_tracked": "objets analysés", "k_updated": "dernière mise à jour",
        "top": "Les {limit} candidats les plus échangés à {market}",
        "note": "Classés par échanges par jour sur les 7 derniers jours. Le ROI est calculé après frais.",
        "item": "Objet", "roi": "ROI", "buy": "Meilleur achat", "sell": "Meilleure vente", "trades": "Échanges/jour",
        "open": "Ouvrir le screener de {market} en direct, avec filtres et tri",
        "hubs": "Autres hubs commerciaux", "crumb": "Screener",
        "chrome": {
            "screener": "Screener", "items": "Tous les objets (EN)", "cta": "Ouvrir le Screener",
            "disclaimer": (
                "Site indépendant, non affilié à CCP Games. EVE Online est une marque de CCP hf. "
                "Outil informatif, pas un conseil en investissement. Données de l'API officielle ESI."
            ),
            "privacy": "Confidentialité",
        },
    },
    "it": {
        "title": "Station trading a {market} (EVE Online): migliori oggetti per ROI | EveMarket Screener",
        "desc": "Quali oggetti conviene scambiare a {market} ({region}): {n} candidati ordinati per ROI, spread e liquidità, aggiornato ogni 5 minuti.",
        "h1": "Station trading a {market}: gli oggetti che conviene scambiare",
        "lede": "{n} oggetti a {market} ({region}) i cui spread, liquidità e storico recente degli scambi li rendono candidati per lo station trading. Prezzi e calcoli si aggiornano ogni 5 minuti dall'API ufficiale ESI.",
        "k_potential": "candidati", "k_tracked": "oggetti analizzati", "k_updated": "ultimo aggiornamento",
        "top": "I {limit} candidati più scambiati a {market}",
        "note": "Ordinati per scambi al giorno negli ultimi 7 giorni. Il ROI è calcolato dopo le commissioni.",
        "item": "Oggetto", "roi": "ROI", "buy": "Miglior acquisto", "sell": "Miglior vendita", "trades": "Scambi/giorno",
        "open": "Apri lo screener di {market} dal vivo, con filtri e ordinamento",
        "hubs": "Altri hub commerciali", "crumb": "Screener",
        "chrome": {
            "screener": "Screener", "items": "Tutti gli oggetti (EN)", "cta": "Apri lo Screener",
            "disclaimer": (
                "Sito indipendente, non affiliato a CCP Games. EVE Online è un marchio di CCP hf. "
                "Strumento informativo, non consulenza di investimento. Dati dall'API ufficiale ESI."
            ),
            "privacy": "Privacy",
        },
    },
}


def market_path(lang: str, slug: str) -> str:
    """Ruta de la portada de un mercado: el inglés vive en la raíz, el resto bajo /{lang}/."""
    return f"/{slug}/" if lang == "en" else f"/{lang}/{slug}/"


def _parse_ts(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _alternates(slug: str) -> str:
    links = "".join(
        f'<link rel="alternate" hreflang="{lang}" href="{BASE_URL}{market_path(lang, slug)}">\n'
        for lang in SITEMAP_LANGS
    )
    return links + f'<link rel="alternate" hreflang="x-default" href="{BASE_URL}{market_path("en", slug)}">\n'


def _render(lang: str, slug: str) -> HTMLResponse:
    conn = _db()
    try:
        market = conn.execute(
            "SELECT market_id, name FROM market WHERE market_id = ? AND enabled = 1", (slug,),
        ).fetchone()
        if market is None:
            return _not_found()
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM item_status WHERE market_id = ? GROUP BY status", (slug,),
        )}
        latest = conn.execute(
            "SELECT MAX(last_evaluated_at) FROM item_status WHERE market_id = ?", (slug,),
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT s.type_id, i.name, s.roi, s.best_buy, s.best_sell, s.avg_daily_order_count_7d "
            "FROM item_status s JOIN item_type i ON i.type_id = s.type_id "
            f"WHERE s.market_id = ? AND s.status IN ({_STATUS_PLACEHOLDERS}) "
            "ORDER BY s.avg_daily_order_count_7d DESC, s.type_id LIMIT ?",
            (slug, *INDEXABLE_STATUSES, TOP_LIMIT),
        ).fetchall()
        hubs = conn.execute(
            "SELECT market_id, name FROM market WHERE enabled = 1 ORDER BY sort_order, market_id",
        ).fetchall()
    finally:
        conn.close()

    text = T[lang]
    name = market["name"]
    region = REGION_NAMES.get(slug, name)
    candidates = sum(counts.get(status, 0) for status in INDEXABLE_STATUSES)
    updated = _parse_ts(latest)
    fresh = updated is not None and datetime.now(timezone.utc) - updated <= MAX_AGE
    robots = "index, follow" if candidates > 0 and fresh else "noindex, follow"

    def fill(template: str) -> str:
        return template.format(market=name, region=region, n=f"{candidates:,}", limit=TOP_LIMIT)

    table_rows = "".join(
        "<tr><td>"
        + (f'<a href="{_e(item_path(r["type_id"], r["name"]))}">{_e(r["name"])}</a>'
           if slug == DEFAULT_MARKET else _e(r["name"]))
        + f'</td><td class="num pos">{_pct(r["roi"])}</td><td class="num">{_isk(r["best_buy"])}</td>'
        f'<td class="num">{_isk(r["best_sell"])}</td>'
        f'<td class="num">{r["avg_daily_order_count_7d"]:,.0f}</td></tr>'
        for r in rows
    )
    table = (
        f"<h2>{_e(fill(text['top']))}</h2><p class=\"muted\">{_e(text['note'])}</p>"
        '<div class="tablewrap"><table class="rank"><thead><tr>'
        f"<th>{_e(text['item'])}</th><th>{_e(text['roi'])}</th><th>{_e(text['buy'])}</th>"
        f"<th>{_e(text['sell'])}</th><th>{_e(text['trades'])}</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table></div>"
        if rows else ""
    )
    current = ' aria-current="page"'
    hub_links = "".join(
        f'<li><a href="{_e(market_path(lang, h["market_id"]))}"'
        f'{current if h["market_id"] == slug else ""}>{_e(h["name"])}</a></li>'
        for h in hubs
    )
    home = lang_path(lang)
    updated_text = updated.strftime("%Y-%m-%d %H:%M UTC") if updated else "—"
    body = (
        f"<h1>{_e(fill(text['h1']))}</h1><p class=\"lede\">{_e(fill(text['lede']))}</p>"
        f'<ul class="chips"><li><b>{candidates:,}</b> {_e(text["k_potential"])}</li>'
        f'<li><b>{sum(counts.values()):,}</b> {_e(text["k_tracked"])}</li>'
        f'<li>{_e(text["k_updated"])}: <b>{_e(updated_text)}</b></li></ul>'
        f'<ul class="hubs" aria-label="{_e(text["hubs"])}">{hub_links}</ul>'
        + table
        + f'<p><a class="cta" href="{_e(home)}?market={_e(slug)}">{_e(fill(text["open"]))}</a></p>'
    )
    path = market_path(lang, slug)
    title, description = fill(text["title"]), fill(text["desc"])
    ld = _json_ld(title, path, [(text["crumb"], home), (name, path)], f"{name} ({region})", lang)
    return _html(_page(
        title, description, path, body, robots, ld, lang=lang, chrome=text["chrome"],
        head_extra=_alternates(slug), home_href=home,
    ))


def sitemap_market_urls(url, lastmod) -> list[str]:
    """Entradas del sitemap: cada portada de mercado activo con datos, en los 5 idiomas."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT m.market_id, MAX(s.last_evaluated_at) AS latest, "
            f"SUM(s.status IN ({_STATUS_PLACEHOLDERS})) AS candidates "
            "FROM market m JOIN item_status s ON s.market_id = m.market_id "
            "WHERE m.enabled = 1 GROUP BY m.market_id ORDER BY m.sort_order",
            INDEXABLE_STATUSES,
        ).fetchall()
    finally:
        conn.close()
    entries = []
    for row in rows:
        if not row["candidates"] or row["market_id"] not in MARKET_SLUGS:
            continue
        alternates = "".join(
            f'<xhtml:link rel="alternate" hreflang="{lang}" href="{BASE_URL}{market_path(lang, row["market_id"])}"/>'
            for lang in SITEMAP_LANGS
        ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{BASE_URL}{market_path("en", row["market_id"])}"/>'
        entries += [
            url(f"{BASE_URL}{market_path(lang, row['market_id'])}", lastmod(row["latest"]), alternates)
            for lang in SITEMAP_LANGS
        ]
    return entries


def _register() -> None:
    """Una ruta fija por mercado e idioma. No se usa un parámetro de ruta (`/{market}/`) porque
    capturaría también `/es/`, `/de/`... (las portadas por idioma, que sirve el frontend)."""
    for lang in SITEMAP_LANGS:
        for slug in MARKET_SLUGS:
            def handler(lang: str = lang, slug: str = slug) -> HTMLResponse:
                return _render(lang, slug)

            router.add_api_route(
                market_path(lang, slug), handler, methods=["GET"], response_class=HTMLResponse,
                include_in_schema=False, name=f"market_page_{lang}_{slug}",
            )


_register()
