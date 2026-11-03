"""Eventos de dominio que los motores emiten y este módulo despacha a notificaciones.

Antes cada motor llamaba notify_*() directo, intercalado con el resto de la lógica de
cada corrida (persistencia, clasificación, etc.) — funciona, pero mezcla "qué pasó" con
"qué hacer con eso". Ahora los motores solo ACUMULAN eventos tipados mientras corren, y
llaman dispatch() una vez al final. La ventaja no es de comportamiento (las mismas
notificaciones salen, en el mismo run) sino de forma: dispatch() es el único lugar que
sabe de notifications/telegram_bot.py. El día que este proyecto necesite un bus de
eventos de verdad (Redis/RabbitMQ, ver BACKLOG.md T5), ese cambio queda contenido acá
adentro — publicar en vez de llamar notify_*() directo — sin tocar scheduler/run.py ni
scheduler/orders_run.py.
"""
from dataclasses import dataclass

from analytics.eve_calculator import EveCalculatorResult
from notifications.telegram_bot import (
    notify_new_opportunity,
    notify_order_closed,
    notify_order_filled,
    notify_position_update,
)


@dataclass
class NewOpportunity:
    """Un ítem pasó a POTENCIAL por primera vez (motor de mercado)."""
    result: EveCalculatorResult


@dataclass
class PositionChanged:
    """Cambió cuántas órdenes te compiten por delante en una orden activa tuya
    (motor de posiciones) — incluye la transición a "recuperaste la primera posición"."""
    item_name: str
    side: str
    price: float
    orders_ahead: int
    price_gap: float
    best_price: float
    recovered: bool = False


@dataclass
class OrderClosed:
    """Una orden activa tuya desapareció: completada, expirada o cancelada
    (motor de posiciones). `wallet_balance` solo se completa para ventas que
    terminaron 'completada' (ahí sí entró ISK a la cuenta)."""
    item_name: str
    side: str
    price: float
    final_state: str
    wallet_balance: float | None = None


@dataclass
class OrderFilled:
    """Se ejecutó total o parcialmente una orden activa tuya: volume_remain bajó desde
    la corrida anterior pero la orden sigue activa (motor de posiciones). Una
    ejecución que deja volume_remain en 0 no pasa por acá — la orden desaparece de las
    activas y la agarra OrderClosed en la corrida siguiente (con wallet_balance si fue
    una venta). `wallet_balance` acá también solo se completa para ventas."""
    item_name: str
    side: str
    price: float
    filled_units: int
    volume_remain: int
    wallet_balance: float | None = None


Event = NewOpportunity | PositionChanged | OrderClosed | OrderFilled


def dispatch(events: list[Event]) -> None:
    """Único punto de contacto entre los motores y notifications/telegram_bot.py."""
    for event in events:
        if isinstance(event, NewOpportunity):
            notify_new_opportunity(event.result)
        elif isinstance(event, PositionChanged):
            notify_position_update(
                event.item_name, event.side, event.price,
                event.orders_ahead, event.price_gap, event.best_price,
                recovered=event.recovered,
            )
        elif isinstance(event, OrderClosed):
            notify_order_closed(
                event.item_name, event.side, event.price, event.final_state,
                wallet_balance=event.wallet_balance,
            )
        elif isinstance(event, OrderFilled):
            notify_order_filled(
                event.item_name, event.side, event.price, event.filled_units, event.volume_remain,
                wallet_balance=event.wallet_balance,
            )
        else:
            raise TypeError(f"Tipo de evento desconocido: {type(event)!r}")
