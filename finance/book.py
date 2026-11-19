"""Recorrido de niveles del libro de órdenes: precio medio ponderado y profundidad."""
from dataclasses import dataclass
from decimal import Decimal

from finance.fees import dec


@dataclass(frozen=True)
class Fill:
    requested: Decimal
    filled: Decimal
    total: Decimal               # ISK pagados/recibidos por lo ejecutado
    average_price: Decimal | None
    shortfall: Decimal           # unidades que el libro no cubre
    levels_used: int


def _walk(levels, units: Decimal, ascending: bool) -> Fill:
    parsed = [(dec(p), dec(v)) for p, v in levels]
    for price, volume in parsed:
        if price <= 0 or volume < 0:
            raise ValueError("nivel de libro inválido")
    parsed.sort(key=lambda lv: lv[0], reverse=not ascending)
    remaining, total, used = units, Decimal(0), 0
    for price, volume in parsed:
        if remaining <= 0:
            break
        if volume == 0:
            continue
        take = min(volume, remaining)
        total += take * price
        remaining -= take
        used += 1
    filled = units - remaining
    avg = (total / filled) if filled > 0 else None
    return Fill(units, filled, total, avg, remaining, used)


def buy_immediate(asks, units) -> Fill:
    """Comprar a mercado: se consumen las ventas más baratas primero."""
    return _walk(asks, dec(units), ascending=True)


def sell_immediate(bids, units) -> Fill:
    """Vender a mercado: se consumen las compras más caras primero."""
    return _walk(bids, dec(units), ascending=False)
