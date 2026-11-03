"""Determina si una orden activa propia quedó undercuteada por el mercado."""


def is_order_undercut(is_buy_order: bool, my_price: float, region_best_buy: float | None,
                       region_best_sell: float | None) -> bool:
    """Compra: te undercutean si alguien ofrece pagar MÁS que vos (best_buy > my_price).
    Venta: te undercutean si alguien vende MÁS BARATO que vos (0 < best_sell < my_price).
    """
    if is_buy_order:
        return region_best_buy is not None and region_best_buy > my_price
    return region_best_sell is not None and 0 < region_best_sell < my_price
