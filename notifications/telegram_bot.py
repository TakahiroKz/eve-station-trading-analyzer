"""Notificaciones vía Telegram: nuevas oportunidades POTENCIAL, cambios de posición
en tus órdenes activas (undercuts), ejecuciones (compra/venta) sobre tus órdenes, y
órdenes tuyas que se completaron/expiraron/cancelaron.

Requiere un bot creado con @BotFather (TELEGRAM_BOT_TOKEN) y el chat_id del usuario
(TELEGRAM_CHAT_ID, se obtiene enviándole /start al bot y consultando
https://api.telegram.org/bot<token>/getUpdates). Degrada sin bloquear el pipeline
si no está configurado.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def _send_message(text: str, context: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.debug("Telegram no configurado; sin notificación (%s)", context)
        return False

    try:
        response = httpx.post(
            f"{API_BASE}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("Fallo al enviar notificación de Telegram (%s)", context)
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
