"""Agrega el libro de órdenes crudo de la ESI a un resumen por ítem.

Vivía como función suelta en scheduler/run.py — es cálculo de negocio (reducir
cientos de miles de órdenes a best_buy/best_sell/volúmenes/conteos por type_id), así
que corresponde acá con el resto de analytics/, no en el orquestador. ingestion/ solo
trae datos crudos de la ESI; scheduler/ solo orquesta ingesta -> análisis -> persistencia.

Además de lo básico calcula la profundidad del libro de cada lado, que es la base del análisis de
competencia: cuántas unidades hay dentro de una banda del 5 % alrededor del mejor precio, la distancia
al siguiente nivel de precio y qué parte del volumen está concentrada en el mejor precio. Son datos de
la REGIÓN completa (igual que los precios), no de una estación. Se guardan como enteros (unidades,
puntos básicos y por mil) para que cada snapshot ocupe poco.
"""

DEPTH_BAND = 0.05  # banda alrededor del mejor precio dentro de la que se cuenta la profundidad


def _side_depth(levels: list[tuple[float, int]], best: float, is_buy: bool) -> tuple[int, int | None, int | None]:
    """(unidades dentro de la banda, distancia al siguiente nivel en puntos básicos, parte del volumen en el
    mejor precio por mil). Distancia y concentración son None si no hay segundo nivel / no hay volumen."""
    limit = best * (1 - DEPTH_BAND) if is_buy else best * (1 + DEPTH_BAND)
    depth = at_best = total = 0
    second: float | None = None
    for price, volume in levels:
        total += volume
        if (price >= limit) if is_buy else (price <= limit):
            depth += volume
        if price == best:
            at_best += volume
        elif (price < best) if is_buy else (price > best):
            if second is None or ((price > second) if is_buy else (price < second)):
                second = price
    gap_bp = None if second is None or best <= 0 else int(round(abs(best - second) / best * 10_000))
    top_permille = int(round(at_best / total * 1000)) if total > 0 else None
    return depth, gap_bp, top_permille


def build_orders_by_type(orders: list[dict]) -> dict[int, dict]:
    """Reduce la lista de órdenes activas a best_buy/best_sell/volúmenes/conteo de órdenes por type_id, más la
    profundidad del libro (buy/sell_depth_5pct, buy/sell_gap_bp, buy/sell_top_permille)."""
    by_type: dict[int, dict] = {}
    levels: dict[tuple[int, bool], list[tuple[float, int]]] = {}
    for order in orders:
        type_id = order["type_id"]
        entry = by_type.setdefault(type_id, {
            "best_buy": None, "best_sell": None, "buy_volume": 0, "sell_volume": 0,
            "buy_order_count": 0, "sell_order_count": 0,
            "buy_depth_5pct": None, "sell_depth_5pct": None, "buy_gap_bp": None, "sell_gap_bp": None,
            "buy_top_permille": None, "sell_top_permille": None,
        })
        is_buy = bool(order["is_buy_order"])
        levels.setdefault((type_id, is_buy), []).append((order["price"], order["volume_remain"]))
        if is_buy:
            entry["buy_volume"] += order["volume_remain"]
            entry["buy_order_count"] += 1
            if entry["best_buy"] is None or order["price"] > entry["best_buy"]:
                entry["best_buy"] = order["price"]
        else:
            entry["sell_volume"] += order["volume_remain"]
            entry["sell_order_count"] += 1
            if entry["best_sell"] is None or order["price"] < entry["best_sell"]:
                entry["best_sell"] = order["price"]

    for (type_id, is_buy), side_levels in levels.items():
        entry = by_type[type_id]
        side = "buy" if is_buy else "sell"
        depth, gap_bp, top_permille = _side_depth(side_levels, entry[f"best_{side}"], is_buy)
        entry[f"{side}_depth_5pct"] = depth
        entry[f"{side}_gap_bp"] = gap_bp
        entry[f"{side}_top_permille"] = top_permille
    return by_type
