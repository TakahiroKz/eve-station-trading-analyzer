"""Filtro de sanidad contra 'órdenes basura' (troll orders).

EVE Online no tiene piso de precio: cualquiera puede poner una orden de compra a 0.01
ISK o de venta a precios absurdos. Si el best_buy/best_sell de la foto de órdenes se
toma tal cual, esas órdenes degeneradas producen spreads de millones de % que no son
oportunidades reales. Se contrasta contra el precio mediano reciente del histórico
(que sí refleja transacciones reales ejecutadas, no órdenes abiertas) para descartarlas.
"""
from dataclasses import dataclass


@dataclass
class SanityConfig:
    # Nombres de campo iguales a las keys de storage/settings_registry.py a propósito
    # (categoría "Filtro de órdenes basura") — así scheduler/run.py arma el config con
    # **kwargs filtrados del dict de settings, sin mapear cada campo a mano.
    sanity_min_ratio: float = 0.2   # best_buy no puede ser < 20% del precio de referencia
    sanity_max_ratio: float = 5.0   # best_sell no puede ser > 500% del precio de referencia


DEFAULT_CONFIG = SanityConfig()


def is_price_sane(best_buy: float, best_sell: float, reference_price: float,
                   config: SanityConfig = DEFAULT_CONFIG) -> bool:
    if reference_price <= 0:
        return False
    if best_buy < reference_price * config.sanity_min_ratio:
        return False
    if best_sell > reference_price * config.sanity_max_ratio:
        return False
    return True
