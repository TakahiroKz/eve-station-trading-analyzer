"""Notificaciones vía Telegram: cambios de posición en tus órdenes activas (undercuts),
ejecuciones (compra/venta) sobre tus órdenes, y órdenes tuyas que se completaron/expiraron/
canceladas. Las nuevas oportunidades POTENCIAL están suspendidas por defecto (ver
notifications/events.py, TELEGRAM_NOTIFY_OPPORTUNITIES); las alertas de servicio las envía el
watchdog (scripts/healthcheck.sh) solo cuando hay una falla y cuando se recupera. Todo se avisa
solo si hay novedades, sin horario fijo.

Requiere un bot creado con @BotFather (TELEGRAM_BOT_TOKEN) y el chat_id del usuario
(TELEGRAM_CHAT_ID, se obtiene enviándole /start al bot y consultando
https://api.telegram.org/bot<token>/getUpdates). Degrada sin bloquear el pipeline
si no está configurado.

El envío es corto y acotado (timeouts de pocos segundos y un único reintento ante un error de
red, un 5xx o un 429). Si aun así falla, el aviso pasa a la cola duradera (notifications/outbox.py)
y se reintenta en las siguientes corridas en lugar de perderse. `notifications/events.py` hace
estos envíos en segundo plano para que un Telegram lento no alargue el ciclo.
"""
import logging
import os
import time

import httpx

from notifications import outbox

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"  # se puede cambiar con TELEGRAM_API_BASE (pruebas)
SEND_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0)
MAX_RETRY_WAIT_SECONDS = 5.0
RETRY_PAUSE_SECONDS = 0.5


def _api_base() -> str:
    return os.environ.get("TELEGRAM_API_BASE", API_BASE).rstrip("/")


def deliver(text: str) -> bool:
    """Un envío con como mucho un reintento. True si Telegram lo aceptó; False si falló por algo
    pasajero (red, 5xx, 429). Un 4xx (token o chat mal configurados) lanza `PermanentError`."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise PermanentError("Telegram no configurado")

    last_error = "sin respuesta"
    for attempt in (1, 2):
        try:
            response = httpx.post(
                f"{_api_base()}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=SEND_TIMEOUT,
            )
        except httpx.TransportError as exc:
            last_error = f"{type(exc).__name__}"
            if attempt == 1:
                time.sleep(RETRY_PAUSE_SECONDS)
            continue

        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            if attempt == 1:
                time.sleep(min(_retry_after(response), MAX_RETRY_WAIT_SECONDS))
            continue
        if response.status_code >= 400:
            raise PermanentError(f"HTTP {response.status_code}")
        return True

    logger.debug("Telegram no respondió tras reintentar: %s", last_error)
    return False


class PermanentError(Exception):
    """Fallo que reintentar no arregla (token/chat inválidos o sin configurar)."""


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.json().get("parameters", {}).get("retry_after", RETRY_PAUSE_SECONDS))
    except Exception:
        return RETRY_PAUSE_SECONDS


def _send_message(text: str, context: str) -> bool:
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        logger.debug("Telegram no configurado; sin notificación (%s)", context)
        return False
    try:
        if deliver(text):
            return True
    except PermanentError as exc:
        logger.error("Fallo al enviar notificación de Telegram (%s): %s", context, exc)
        return False
    except Exception:
        logger.exception("Fallo al enviar notificación de Telegram (%s)", context)
        return False

    # Falló por algo pasajero: no se pierde, se reintenta en las siguientes corridas.
    logger.error("Fallo al enviar notificación de Telegram (%s): se reintentará", context)
    outbox.enqueue(text, context)
    return False


def notify_new_opportunity(result) -> bool:
    """result: EveCalculatorResult. Devuelve True si se envió, False si degradó."""
    inversion = result.unidades_sugeridas * result.buy
    beneficio_total = result.unidades_sugeridas * result.beneficio
    text = (
        f"🎯 Nueva oportunidad POTENCIAL: {result.item}\n\n"
        f"Buy: {result.buy:,.2f} | Sell: {result.sell:,.2f}\n"
        f"Beneficio/u: {result.beneficio:,.2f} ISK\n"
        f"Spread: {result.spread_bruto:.2%} ({result.evaluacion_spread})\n"
        f"ROI: {result.roi:.2%}\n"
        f"Liquidez: {result.liquidez} (posición {result.posicion_vs_volumen:.2%})\n\n"
        f"💰 Comprá ~{result.unidades_sugeridas:,} unidades (~{inversion:,.2f} ISK)\n"
        f"Beneficio total estimado: ~{beneficio_total:,.2f} ISK\n\n"
        f"{result.recomendacion}"
    )
    return _send_message(text, f"oportunidad {result.item}")


def notify_position_update(item_name: str, side: str, my_price: float, orders_ahead: int,
                            price_gap: float, best_price: float, recovered: bool = False) -> bool:
    """side: 'compra' o 'venta'. Motor de posiciones (cada 5 min): cambió la cantidad
    de órdenes que te ganan el precio en una orden activa tuya, contra el libro de
    órdenes real de ese ítem (no un agregado). `recovered=True` es el aviso positivo
    de que volviste a ser la primera orden tras haber estado undercuteado."""
    if recovered:
        text = (
            f"✅ Recuperaste la primera posición: {item_name} ({side})\n\n"
            f"Tu precio: {my_price:,.2f} ISK ya es el mejor del libro."
        )
        return _send_message(text, f"posicion recuperada {item_name}")

    plural = "orden" if orders_ahead == 1 else "órdenes"
    text = (
        f"⚠️ Te undercutearon: {item_name} ({side})\n\n"
        f"{orders_ahead} {plural} por delante tuyo\n"
        f"Tu precio: {my_price:,.2f} ISK\n"
        f"Primera orden del libro: {best_price:,.2f} ISK (diferencia: {price_gap:,.2f} ISK)"
    )
    return _send_message(text, f"posicion {item_name}")


def notify_order_closed(item_name: str, side: str, price: float, final_state: str,
                         wallet_balance: float | None = None) -> bool:
    """final_state: 'completada' (volume_remain llegó a 0), 'expirada' o 'cancelada'.
    `wallet_balance`: saldo actual del wallet tras el cierre — solo se pasa para ventas
    completadas (ahí sí entró ISK a la cuenta); se omite el resto de los casos."""
    emoji = "✅" if final_state == "completada" else "ℹ️"
    text = (
        f"{emoji} Orden {final_state}: {item_name} ({side})\n\n"
        f"Precio: {price:,.2f} ISK"
    )
    if wallet_balance is not None:
        text += f"\nSaldo en la cuenta: {wallet_balance:,.2f} ISK"
    return _send_message(text, f"orden {final_state} {item_name}")


def notify_trend_change(item_name: str, market_name: str, label: str, change: float, threshold: float,
                        ops_per_day: float, sides: tuple[str, ...]) -> bool:
    """Cambio de tendencia de precio confirmado en dos lecturas diarias seguidas, solo para ítems en
    los que hay una orden activa. Describe lo ocurrido; no es una predicción."""
    emoji, word = ("📈", "al alza") if label == "up" else ("📉", "a la baja")
    orders = " y ".join(f"orden de {s}" for s in sides) or "orden activa"
    text = (
        f"{emoji} Tendencia {word}: {item_name} ({market_name})\n\n"
        f"Precio medio de 7 días: {change:+.1%} frente a la semana anterior "
        f"(umbral de este ítem: ±{threshold:.1%})\n"
        f"Confirmada en dos lecturas diarias seguidas · ~{ops_per_day:,.0f} operaciones/día\n"
        f"Tienes {orders} en este ítem.\n\n"
        f"Es una descripción de lo ocurrido, no una predicción."
    )
    return _send_message(text, f"tendencia {item_name}")


def notify_order_filled(item_name: str, side: str, price: float, filled_units: int,
                         volume_remain: int, wallet_balance: float | None = None) -> bool:
    """Motor de posiciones (cada 5 min): se ejecutó total o parcialmente una orden activa
    tuya — volume_remain bajó desde la corrida anterior. Una ejecución que deja
    volume_remain en 0 no pasa por acá (ver notifications/events.py: la agarra
    notify_order_closed en la corrida siguiente, con wallet_balance si fue venta).
    `wallet_balance`: saldo actual del wallet — solo se pasa para ventas (ahí sí entró
    ISK a la cuenta)."""
    emoji = "💰" if side == "venta" else "🛒"
    verbo = "vendieron" if side == "venta" else "compraron"
    text = (
        f"{emoji} Ejecución en tu orden: {item_name} ({side})\n\n"
        f"Se {verbo} {filled_units:,} unidades a {price:,.2f} ISK\n"
        f"Quedan {volume_remain:,} unidades en la orden"
    )
    if wallet_balance is not None:
        text += f"\nSaldo en la cuenta: {wallet_balance:,.2f} ISK"
    return _send_message(text, f"ejecucion {item_name}")
