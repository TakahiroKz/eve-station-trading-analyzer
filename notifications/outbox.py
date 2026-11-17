"""Cola duradera de avisos de Telegram que no se pudieron enviar.

Un aviso que falla por un problema pasajero de red no se pierde: se guarda en la tabla
`notification_outbox` y se reintenta en las siguientes corridas de los motores (cada 5 min),
durante MAX_AGE_MINUTES minutos y hasta MAX_ATTEMPTS intentos. Antes se descartaba, y como el
ítem ya figuraba como POTENCIAL no se volvía a avisar.

Los dos motores (mercado y posiciones) pueden vaciar la cola a la vez: cada fila se "reclama"
antes de enviarla (claimed_at) para que no salga duplicada. Todo es tolerante a fallos: un
error con la base nunca debe tumbar un ciclo, solo se anota en el log.
"""
import logging
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable

from storage.db import NOTIFICATION_OUTBOX_SCHEMA, get_connection

logger = logging.getLogger(__name__)

MAX_AGE_MINUTES = 30
MAX_ATTEMPTS = 5
CLAIM_SECONDS = 90  # una fila reclamada por otro proceso no se vuelve a tomar durante este tiempo
MAX_PER_DRAIN = 20


def _db_path() -> str:
    return os.environ.get("DB_PATH", "./storage/market.db")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _connect(create: bool = True) -> sqlite3.Connection | None:
    path = _db_path()
    if not create and not os.path.exists(path):
        return None
    conn = get_connection(path)
    conn.executescript(NOTIFICATION_OUTBOX_SCHEMA)
    return conn


def enqueue(text: str, context: str, error: str | None = None) -> bool:
    """Guarda un aviso para reintentarlo. No duplica uno idéntico que ya está pendiente."""
    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO notification_outbox (text, context, created_at, attempts, last_error) "
                "SELECT ?, ?, ?, 0, ? WHERE NOT EXISTS "
                "(SELECT 1 FROM notification_outbox WHERE text = ? AND context = ?)",
                (text, context, _iso(_now()), error, text, context),
            )
            conn.commit()
        finally:
            conn.close()
        logger.warning("Aviso de Telegram en cola para reintentar (%s)", context)
        return True
    except Exception:
        logger.exception("No se pudo guardar el aviso de Telegram en la cola (%s)", context)
        return False


def pending_count() -> int:
    """Filas en la cola; 0 si la base todavía no existe (no la crea)."""
    try:
        conn = _connect(create=False)
        if conn is None:
            return 0
        try:
            return conn.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        logger.exception("No se pudo leer la cola de avisos de Telegram")
        return 0


def drain(deliver: Callable[[str], bool], max_workers: int = 4) -> int:
    """Reintenta los avisos pendientes con `deliver(text) -> bool`. Borra los enviados, descarta
    los que superaron la edad o los intentos máximos y devuelve cuántos salieron."""
    try:
        conn = _connect(create=False)
        if conn is None:
            return 0
        try:
            now = _now()
            stale = conn.execute(
                "DELETE FROM notification_outbox WHERE created_at < ? OR attempts >= ?",
                (_iso(now - timedelta(minutes=MAX_AGE_MINUTES)), MAX_ATTEMPTS),
            ).rowcount
            if stale:
                logger.warning("Avisos de Telegram descartados por antigüedad o intentos: %d", stale)
            candidates = conn.execute(
                "SELECT id, text, context FROM notification_outbox "
                "WHERE claimed_at IS NULL OR claimed_at < ? ORDER BY id LIMIT ?",
                (_iso(now - timedelta(seconds=CLAIM_SECONDS)), MAX_PER_DRAIN),
            ).fetchall()
            claimed = []
            for row in candidates:
                taken = conn.execute(
                    "UPDATE notification_outbox SET claimed_at = ?, attempts = attempts + 1 "
                    "WHERE id = ? AND (claimed_at IS NULL OR claimed_at < ?)",
                    (_iso(now), row["id"], _iso(now - timedelta(seconds=CLAIM_SECONDS))),
                ).rowcount
                if taken:
                    claimed.append(row)
            conn.commit()
            if not claimed:
                return 0

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                outcomes = list(pool.map(lambda r: _try(deliver, r["text"]), claimed))

            sent = 0
            for row, ok in zip(claimed, outcomes):
                if ok:
                    conn.execute("DELETE FROM notification_outbox WHERE id = ?", (row["id"],))
                    sent += 1
                else:
                    conn.execute(
                        "UPDATE notification_outbox SET claimed_at = NULL, last_error = ? WHERE id = ?",
                        ("reintento fallido", row["id"]),
                    )
            conn.commit()
            if sent:
                logger.info("Avisos de Telegram reenviados desde la cola: %d de %d", sent, len(claimed))
            return sent
        finally:
            conn.close()
    except Exception:
        logger.exception("Fallo al vaciar la cola de avisos de Telegram")
        return 0


def _try(deliver: Callable[[str], bool], text: str) -> bool:
    try:
        return bool(deliver(text))
    except Exception:
        logger.exception("Fallo al reenviar un aviso de Telegram")
        return False
