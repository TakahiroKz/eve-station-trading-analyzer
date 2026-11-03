"""Motor de posiciones: revisa tus órdenes activas contra el libro de órdenes REAL
de cada ítem (no un agregado) y notifica solo cuando cambia tu posición. Pensado para
correr cada 5 minutos — separado del motor de mercado (scheduler/run.py, cada 4hs) para
que la revisión de tus propias órdenes tenga una cadencia mucho más ágil que el
screening completo de la región.

Uso:
    python -m scheduler.orders_run
"""
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from analytics.order_position import compute_position
from ingestion.esi_client import DEFAULT_BASE_URL, EsiClient
from ingestion.session import get_valid_session
from ingestion.wallet import get_current_wallet_balance
from notifications.events import OrderClosed, OrderFilled, PositionChanged, dispatch
from storage.db import (
    delete_character_order,
    get_active_character_order_ids,
    get_character_order,
    get_connection,
    init_db,
    insert_character_order_closed,
    insert_character_order_fill,
    upsert_character_order,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _resolve_closed_order_state(client: EsiClient, character_id: int, access_token: str,
                                 order_id: int, volume_remain: int) -> str:
    """La ESI solo distingue 'cancelled'/'expired' en el historial — 'completada' se infiere:
    volume_remain == 0 en la última foto que tuvimos significa que se llenó del todo antes
    de desaparecer de las activas, aunque la ESI la etiquete como 'expired' internamente.
    """
    try:
        history = client.get_character_order_history(character_id, access_token)
    except Exception:
        logger.exception("Fallo al traer historial de órdenes del personaje")
        return "cerrada"

    match = next((o for o in history if o["order_id"] == order_id), None)
    if match is None:
        return "completada" if volume_remain == 0 else "cerrada"
    if match.get("state") == "cancelled":
        return "cancelada"
    if match.get("volume_remain", volume_remain) == 0:
        return "completada"
    return "expirada"


def _item_name(conn, type_id: int) -> str:
    row = conn.execute("SELECT name FROM item_type WHERE type_id = ?", (type_id,)).fetchone()
    return row["name"] if row else f"type_{type_id}"


def check_character_orders(client: EsiClient, db_path: str, notify: bool = True) -> None:
    """Recorre TODAS tus órdenes activas (cualquier región) y para cada una trae el
    libro de órdenes real de ese ítem+lado (la ESI permite filtrar
    /markets/{region_id}/orders/ por type_id), para calcular cuántas órdenes te
    compiten por delante y por cuánto precio. Notifica solo si cambia algo desde la
    corrida anterior: pasás a estar undercuteado, cambia la cantidad de órdenes por
    delante, recuperás la primera posición, o se ejecutó (total o parcialmente) una
    compra/venta tuya (volume_remain bajó). Degrada sin bloquear si no hay sesión
    OAuth (misma política que el wallet).

    `notify=False` persiste los cambios igual pero no dispara Telegram — lo usa el
    refresco manual desde la app (POST /api/character-orders/refresh) para no
    reenviar avisos de algo que el motor de 5 min ya notificó o va a notificar."""
    session = get_valid_session()
    if session is None:
        logger.info("Sin sesión ESI autenticada; se omite el chequeo de posiciones.")
        return
    access_token, character_id = session

    conn = get_connection(db_path)
    try:
        try:
            orders = client.get_character_orders(character_id, access_token)
        except Exception:
            logger.exception("Fallo al traer órdenes activas del personaje")
            return

        now = datetime.now(timezone.utc).isoformat()
        seen_order_ids = set()
        events: list = []

        for order in orders:
            order_id = order["order_id"]
            seen_order_ids.add(order_id)
            type_id = order["type_id"]
            order_region_id = order["region_id"]
            # is_buy_order es opcional en el schema de /characters/{id}/orders/ de la ESI:
            # se omite (no viene como False explícito) cuando la orden es de venta.
            is_buy_order = order.get("is_buy_order", False)
            price = order["price"]

            try:
                book = client.get_orders(
                    order_region_id, order_type="buy" if is_buy_order else "sell", type_id=type_id,
                )
            except Exception:
                logger.exception("Fallo al traer el libro de órdenes de type_id=%s", type_id)
                book = [{"order_id": order_id, "price": price}]

            position = compute_position(is_buy_order, order_id, price, book)
            # compute_position() prefiere el precio del libro público sobre `price` cuando
            # la propia orden ya aparece ahí (ver su docstring) — más confiable que
            # /characters/{id}/orders/, que puede quedar atrás tras un reprice reciente.
            price = position.my_price
            is_undercut = position.orders_ahead > 0

            previous = get_character_order(conn, order_id)
            previous_orders_ahead = previous["orders_ahead"] if previous else None
            first_seen_at = previous["first_seen_at"] if previous else now

            side = "compra" if is_buy_order else "venta"

            if previous is not None and order["volume_remain"] < previous["volume_remain"]:
                filled_units = previous["volume_remain"] - order["volume_remain"]
                # Saldo de la cuenta: solo tiene sentido para ventas (ahí sí entró ISK) —
                # igual que en el cierre de orden completada, ver más abajo.
                fill_wallet_balance = get_current_wallet_balance() if not is_buy_order else None
                events.append(OrderFilled(
                    _item_name(conn, type_id), side, price, filled_units,
                    order["volume_remain"], fill_wallet_balance,
                ))
                # Historial persistente del evento (antes solo viajaba a Telegram vía
                # dispatch() y se perdía apenas pasaba el mensaje) — el dashboard lo lee
                # de acá, no del `events` en memoria.
                insert_character_order_fill(conn, {
                    "order_id": order_id, "type_id": type_id, "is_buy_order": is_buy_order,
                    "price": price, "filled_units": filled_units,
                    "volume_remain": order["volume_remain"], "filled_at": now,
                })

            if is_undercut and previous_orders_ahead != position.orders_ahead:
                events.append(PositionChanged(
                    _item_name(conn, type_id), side, price,
                    position.orders_ahead, position.price_gap, position.best_price,
                ))
            elif not is_undercut and previous_orders_ahead:
                events.append(PositionChanged(
                    _item_name(conn, type_id), side, price, 0, 0.0, price, recovered=True,
                ))

            upsert_character_order(conn, {
                "order_id": order_id, "type_id": type_id, "region_id": order_region_id,
                "is_buy_order": is_buy_order, "price": price,
                "volume_remain": order["volume_remain"], "volume_total": order["volume_total"],
                "issued": order["issued"], "is_undercut": is_undercut,
                "orders_ahead": position.orders_ahead, "price_gap": position.price_gap,
                "best_price": position.best_price,
                "first_seen_at": first_seen_at, "last_seen_at": now,
            })

        closed_order_ids = get_active_character_order_ids(conn) - seen_order_ids
        for order_id in closed_order_ids:
            previous = get_character_order(conn, order_id)
            if previous is None:
                continue
            final_state = _resolve_closed_order_state(
                client, character_id, access_token, order_id, previous["volume_remain"],
            )
            item_name = _item_name(conn, previous["type_id"])
            side = "compra" if previous["is_buy_order"] else "venta"

            insert_character_order_closed(conn, {
                "order_id": order_id, "type_id": previous["type_id"],
                "is_buy_order": previous["is_buy_order"], "price": previous["price"],
                "final_state": final_state, "closed_at": now,
            })

            # Saldo de la cuenta: solo tiene sentido mostrarlo cuando de verdad entró ISK
            # (una venta que se completó) — para canceladas/expiradas, o para compras, no
            # hubo movimiento de dinero, así que no vale la pena gastar la llamada a la ESI.
            wallet_balance = None
            if final_state == "completada" and not previous["is_buy_order"]:
                wallet_balance = get_current_wallet_balance()

            events.append(OrderClosed(item_name, side, previous["price"], final_state, wallet_balance))
            delete_character_order(conn, order_id)

        conn.commit()
        if notify:
            dispatch(events)
        logger.info("Posiciones revisadas: %d activas, %d cerradas esta corrida",
                    len(seen_order_ids), len(closed_order_ids))
    finally:
        conn.close()


def _init_db_with_retry(db_path: str, attempts: int = 2, delay_seconds: float = 5.0) -> None:
    """init_db() ya espera hasta 30s por PRAGMA busy_timeout si el motor de mercado
    tiene una escritura larga en curso (ver storage/db.py) — este reintento es una red
    de seguridad extra para el caso residual de que ni así alcance, no la defensa
    principal. Sin esto, un `sqlite3.OperationalError: database is locked` puntual
    abortaba la corrida entera de 5 min sin revisar ni una orden."""
    for attempt in range(1, attempts + 1):
        try:
            init_db(db_path)
            return
        except sqlite3.OperationalError:
            if attempt == attempts:
                raise
            logger.warning(
                "init_db() chocó con la base ocupada (intento %d/%d), reintentando en %.0fs",
                attempt, attempts, delay_seconds,
            )
            time.sleep(delay_seconds)


def main() -> int:
    load_dotenv()
    base_url = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL)
    user_agent = os.environ.get("ESI_USER_AGENT", "eve-market-screener")
    db_path = os.environ.get("DB_PATH", "./storage/market.db")

    _init_db_with_retry(db_path)
    with EsiClient(base_url=base_url, user_agent=user_agent) as client:
        check_character_orders(client, db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
