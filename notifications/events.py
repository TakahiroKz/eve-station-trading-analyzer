"""Eventos de dominio que los motores emiten y este módulo despacha a notificaciones.

Antes cada motor llamaba notify_*() directo, intercalado con el resto de la lógica de
cada corrida (persistencia, clasificación, etc.) — funciona, pero mezcla "qué pasó" con
"qué hacer con eso". Ahora los motores solo ACUMULAN eventos tipados mientras corren, y
llaman dispatch() una vez al final. La ventaja no es de comportamiento (las mismas
notificaciones salen, en el mismo run) sino de forma: dispatch() es el único lugar que
sabe de notifications/telegram_bot.py. El día que este proyecto necesite un bus de
eventos de verdad (Redis/RabbitMQ), ese cambio queda contenido acá
adentro — publicar en vez de llamar notify_*() directo — sin tocar scheduler/run.py ni
scheduler/orders_run.py.

Los envíos van en segundo plano (un pool de hilos): dispatch() solo los encola y vuelve al
instante, así un Telegram lento no alarga el ciclo. Cada motor llama a flush_notifications()
al final, después de escribir su línea de "Pipeline completo", para esperar un rato razonable
a que salgan y reintentar los avisos atrasados de la cola duradera (notifications/outbox.py).
"""
import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from analytics.eve_calculator import EveCalculatorResult
from notifications import outbox
from notifications.telegram_bot import (
    deliver,
    notify_new_opportunity,
    notify_order_closed,
    notify_order_filled,
    notify_position_update,
    notify_trend_change,
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


@dataclass
class TrendChanged:
    """El precio de un ítem en el que tienes una orden activa lleva dos lecturas diarias seguidas
    subiendo o bajando por encima del umbral propio del ítem (motor de mercado)."""
    item_name: str
    market_name: str
    label: str            # 'up' o 'down'
    change: float         # fracción: 0.12 = +12 %
    threshold: float
    ops_per_day: float
    sides: tuple[str, ...]


Event = NewOpportunity | PositionChanged | OrderClosed | OrderFilled | TrendChanged

logger = logging.getLogger(__name__)

MAX_PARALLEL_SENDS = 4
DEFAULT_FLUSH_TIMEOUT_SECONDS = 15.0

_pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL_SENDS, thread_name_prefix="notify")
_pending: list[Future] = []


def opportunity_notifications_enabled() -> bool:
    """Los avisos de oportunidades nuevas están suspendidos (demasiada información). Se pueden
    volver a activar con TELEGRAM_NOTIFY_OPPORTUNITIES=1. Los avisos de tus órdenes y las alertas
    de servicio no dependen de este interruptor."""
    return os.environ.get("TELEGRAM_NOTIFY_OPPORTUNITIES", "0").strip() == "1"


def _safe(fn, *args, **kwargs):
    """Un fallo al enviar nunca debe propagarse a un motor: se anota y se sigue."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("Fallo inesperado al despachar una notificación")
        return False


def _real_submit(fn, *args, **kwargs) -> None:
    _pending.append(_pool.submit(_safe, fn, *args, **kwargs))


_submit = _real_submit  # los tests lo reemplazan para ejecutar los envíos en línea


def dispatch(events: list[Event]) -> None:
    """Único punto de contacto entre los motores y notifications/telegram_bot.py. Encola los
    envíos en segundo plano y vuelve sin esperar (ver flush_notifications)."""
    for event in events:
        if isinstance(event, NewOpportunity):
            if opportunity_notifications_enabled():
                _submit(notify_new_opportunity, event.result)
        elif isinstance(event, PositionChanged):
            _submit(
                notify_position_update,
                event.item_name, event.side, event.price,
                event.orders_ahead, event.price_gap, event.best_price,
                recovered=event.recovered,
            )
        elif isinstance(event, OrderClosed):
            _submit(
                notify_order_closed,
                event.item_name, event.side, event.price, event.final_state,
                wallet_balance=event.wallet_balance,
            )
        elif isinstance(event, OrderFilled):
            _submit(
                notify_order_filled,
                event.item_name, event.side, event.price, event.filled_units, event.volume_remain,
                wallet_balance=event.wallet_balance,
            )
        elif isinstance(event, TrendChanged):
            _submit(
                notify_trend_change,
                event.item_name, event.market_name, event.label, event.change,
                event.threshold, event.ops_per_day, event.sides,
            )
        else:
            raise TypeError(f"Tipo de evento desconocido: {type(event)!r}")


def flush_notifications(timeout: float = DEFAULT_FLUSH_TIMEOUT_SECONDS) -> None:
    """Reintenta los avisos atrasados de la cola y espera, hasta `timeout` segundos, a que
    terminen los envíos en curso. Lo que no salga a tiempo sigue en segundo plano: el proceso
    espera a esos hilos al terminar, y un envío que falla pasa a la cola para la siguiente corrida."""
    if outbox.pending_count():
        _submit(outbox.drain, deliver)
    pending = list(_pending)
    _pending.clear()
    if not pending:
        return
    _, not_done = wait(pending, timeout=timeout)
    if not_done:
        logger.warning("%d aviso(s) de Telegram siguen enviándose en segundo plano", len(not_done))
