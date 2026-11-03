"""Agrega el libro de órdenes crudo de la ESI a un resumen por ítem.

Vivía como función suelta en scheduler/run.py — es cálculo de negocio (reducir
cientos de miles de órdenes a best_buy/best_sell/volúmenes/conteos por type_id), así
que corresponde acá con el resto de analytics/, no en el orquestador. ingestion/ solo
trae datos crudos de la ESI; scheduler/ solo orquesta ingesta -> análisis -> persistencia.
"""


def build_orders_by_type(orders: list[dict]) -> dict[int, dict]:
    """Reduce la lista de órdenes activas a best_buy/best_sell/volúmenes/conteo de órdenes por type_id."""
    by_type: dict[int, dict] = {}
    for order in orders:
        type_id = order["type_id"]
        entry = by_type.setdefault(type_id, {
            "best_buy": None, "best_sell": None, "buy_volume": 0, "sell_volume": 0,
            "buy_order_count": 0, "sell_order_count": 0,
        })
        if order["is_buy_order"]:
            entry["buy_volume"] += order["volume_remain"]
            entry["buy_order_count"] += 1
            if entry["best_buy"] is None or order["price"] > entry["best_buy"]:
                entry["best_buy"] = order["price"]
        else:
            entry["sell_volume"] += order["volume_remain"]
            entry["sell_order_count"] += 1
            if entry["best_sell"] is None or order["price"] < entry["best_sell"]:
                entry["best_sell"] = order["price"]
    return by_type
