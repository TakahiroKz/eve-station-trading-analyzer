"""Helpers compartidos entre backend/api/main.py (rutas públicas) y
backend/api/private.py (rutas privadas, detrás de Cloudflare Access) — separado
para que ninguno de los dos módulos tenga que importar del otro."""
import os
import sqlite3

from fastapi import HTTPException, Request


def _db() -> sqlite3.Connection:
    db_path = os.environ.get("DB_PATH", "./storage/market.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Los motores (mercado cada 4h, posiciones cada 5min) escriben al mismo archivo
    # desde procesos separados — sin esto, un PUT (ej. Ajustes) que choca con una
    # escritura en curso tira "database is locked" al toque en vez de esperar.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


ITEM_JOIN = (
    "FROM item_status s "
    "JOIN item_type i ON i.type_id = s.type_id "
    "LEFT JOIN item_category c ON c.type_id = s.type_id"
)
ITEM_SELECT_COLS = "s.*, i.name, c.category_id, c.category_name, c.group_id, c.group_name"


def require_cf_access_header(request: Request) -> None:
    """Defensa en profundidad para las rutas de /api/private — Cloudflare Access ya
    bloquea este prefijo en el borde antes de que la request llegue acá; esto es
    solo una red de seguridad extra por si la Access Application se borra o el path
    rule se desconfigura. Chequea que venga un header con pinta de JWT (3 segmentos
    separados por '.'), SIN verificar la firma (eso ya lo hizo Cloudflare) — no
    detecta una policy de Access aflojada a "cualquiera", solo la ausencia total del
    control de Access."""
    jwt = request.headers.get("Cf-Access-Jwt-Assertion", "")
    if jwt.count(".") != 2:
        raise HTTPException(401, "Acceso restringido (falta la sesión de Cloudflare Access).")
