"""Libro de órdenes real de UNA estación para UN ítem (ESI público), para simular compras y ventas inmediatas.

El libro de la región no sirve para esto: una orden en otra estación no se puede ejecutar desde la tuya. Se pide el libro
del ítem en la región, se filtra por la estación y se agrupa por precio (máx. 200 niveles por lado). Caché de 60 s por
(región, estación, ítem). Sin reintentos largos: corre dentro de la petición del jugador.
Limitación conocida: no se modela el volumen mínimo de cada orden ni el alcance (range) de las órdenes de compra.
"""
import os
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

DEFAULT_BASE_URL = "https://esi.evetech.net/latest"
CACHE_TTL = 60.0
CACHE_MAX = 512
MAX_PAGES = 40
MAX_LEVELS = 200
HTTP_TIMEOUT = 10.0

_lock = threading.Lock()
_cache: dict[tuple[int, int, int], tuple[float, dict]] = {}


class BookUnavailable(Exception):
    """ESI no respondió o devolvió algo inesperado."""


def _page(base: str, region_id: int, type_id: int, page: int) -> tuple[list, int]:
    try:
        response = httpx.get(
            f"{base}/markets/{region_id}/orders/", params={"type_id": type_id, "order_type": "all", "page": page},
            headers={"Accept": "application/json", "User-Agent": os.environ.get("ESI_USER_AGENT", "eve-market-screener")},
            timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise BookUnavailable("red") from exc
    if response.status_code == 404:
        return [], 1                       # ESI responde 404 cuando el ítem no tiene órdenes en la región
    if response.status_code != 200:
        raise BookUnavailable(f"http {response.status_code}")
    try:
        data = response.json()
        pages = int(response.headers.get("X-Pages", 1))
    except (ValueError, TypeError) as exc:
        raise BookUnavailable("respuesta") from exc
    if not isinstance(data, list):
        raise BookUnavailable("respuesta")
    return data, max(1, pages)


def _aggregate(orders: list, station_id: int, is_buy: bool) -> list[list[str]]:
    levels: dict[Decimal, int] = {}
    for order in orders:
        if order.get("location_id") != station_id or bool(order.get("is_buy_order")) != is_buy:
            continue
        try:
            price = Decimal(str(order["price"]))
            volume = int(order["volume_remain"])
        except (KeyError, InvalidOperation, ValueError, TypeError):
            continue
        if price <= 0 or volume <= 0 or not price.is_finite():
            continue
        levels[price] = levels.get(price, 0) + volume
    ordered = sorted(levels.items(), key=lambda kv: kv[0], reverse=is_buy)[:MAX_LEVELS]
    return [[format(price, "f"), str(volume)] for price, volume in ordered]


def fetch_station_book(region_id: int, station_id: int, type_id: int, now: float | None = None) -> dict:
    """{asks: [[precio, unidades]…] (más baratas primero), bids: (más caras primero), fetched_at, cached}."""
    now = time.monotonic() if now is None else now
    key = (region_id, station_id, type_id)
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return {**hit[1], "cached": True}
    base = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    orders: list = []
    page, pages = 1, 1
    while page <= pages and page <= MAX_PAGES:
        chunk, pages = _page(base, region_id, type_id, page)
        orders.extend(chunk)
        page += 1
    book = {"asks": _aggregate(orders, station_id, is_buy=False), "bids": _aggregate(orders, station_id, is_buy=True),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[key] = (now, book)
    return {**book, "cached": False}


def clear_cache() -> None:
    with _lock:
        _cache.clear()
