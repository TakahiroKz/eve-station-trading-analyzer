"""Posición de una orden propia contra el libro de órdenes REAL de ese ítem+lado
(no un agregado): cuántas órdenes compiten por delante y por cuánto precio."""

from dataclasses import dataclass


@dataclass
class OrderPosition:
    orders_ahead: int
    price_gap: float
    best_price: float
    my_price: float


def compute_position(is_buy_order: bool, my_order_id: int, my_price: float,
                      book: list[dict]) -> OrderPosition:
    """`book`: órdenes del mismo type_id + lado (is_buy_order), tal como las devuelve
    GET /markets/{region_id}/orders/?type_id=... — incluye la orden propia.

    Compra: gana quien ofrece pagar MÁS. Venta: gana quien pide MENOS.
    `price_gap` siempre es >= 0: cuánto ISK me separa de la primera orden (0 si soy
    la primera). `best_price` es el precio de esa primera orden (el mío si voy primero).

    `my_price` es el fallback si mi propia orden no aparece en `book` — pero si aparece,
    se usa el precio DE AHÍ en vez del pasado por parámetro (`OrderPosition.my_price`
    devuelve el que efectivamente se usó). El motivo: /characters/{id}/orders/ puede
    quedar unos minutos atrás del precio real después de un reajuste (reprice sin
    cancelar/recrear la orden) — el libro público de la región se actualiza más rápido,
    así que si mi orden ya aparece ahí con un precio distinto, ese es el confiable.
    """
    own_price_in_book = next((o["price"] for o in book if o["order_id"] == my_order_id), None)
    effective_price = my_price if own_price_in_book is None else own_price_in_book

    competitor_prices = [o["price"] for o in book if o["order_id"] != my_order_id]

    if is_buy_order:
        best_price = max([*competitor_prices, effective_price])
        orders_ahead = sum(1 for p in competitor_prices if p > effective_price)
        price_gap = max(best_price - effective_price, 0.0)
    else:
        best_price = min([*competitor_prices, effective_price])
        orders_ahead = sum(1 for p in competitor_prices if p < effective_price)
        price_gap = max(effective_price - best_price, 0.0)

    return OrderPosition(
        orders_ahead=orders_ahead, price_gap=price_gap, best_price=best_price, my_price=effective_price,
    )
