import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage.settings_registry import SETTINGS

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_MARKET = "jita"

# Los cinco hubs comerciales principales de EVE. Cada mercado es su REGIÓN (como Jita desde el
# principio). (market_id, nombre, region_id, system_id del hub, orden, activo por defecto)
MARKETS_SEED = (
    ("jita", "Jita", 10000002, 30000142, 1, 1),
    ("amarr", "Amarr", 10000043, 30002187, 2, 0),
    ("dodixie", "Dodixie", 10000032, 30002659, 3, 0),
    ("rens", "Rens", 10000030, 30002510, 4, 0),
    ("hek", "Hek", 10000042, 30002053, 5, 0),
)

# Tablas que pasan a tener market_id en la clave (ver _migrate_to_multimarket).
MULTIMARKET_TABLES = (
    "market_history", "market_snapshot", "item_status", "item_status_history", "opportunity_log",
)
PRE_MARKET_SUFFIX = "_pre_market"


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Dos motores (mercado cada 4h, posiciones cada 5min) y la API escriben al mismo
    # archivo desde procesos separados — sin esto, un choque con una escritura en
    # curso tira "database is locked" al toque en vez de esperar y reintentar.
    # 30s (no 5s): medido en producción que el motor de mercado puede mantener una
    # transacción abierta ~40s entre commits (antes cada 500 filas, bajado a 100 acá
    # mismo por esto) — con 5s, el motor de posiciones (cada 5 min) chocaba contra esa
    # ventana ~9% de las veces y la corrida entera abortaba sin revisar las órdenes.
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _table_sql(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row["sql"] if row else None


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Migraciones idempotentes para bases ya creadas con un esquema anterior.

    SQLite no soporta ALTER TABLE para cambiar un CHECK constraint, así que
    item_status (estado VIGENTE, se regenera completo en cada corrida — no es
    historial) se reconstruye si le falta el status POTENCIAL_SIN_ORDENES.
    """
    if _table_sql(conn, "market_snapshot") is not None:
        if not _column_exists(conn, "market_snapshot", "buy_order_count"):
            conn.execute("ALTER TABLE market_snapshot ADD COLUMN buy_order_count INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "market_snapshot", "sell_order_count"):
            conn.execute("ALTER TABLE market_snapshot ADD COLUMN sell_order_count INTEGER NOT NULL DEFAULT 0")

    item_status_sql = _table_sql(conn, "item_status")
    if item_status_sql is not None and "POTENCIAL_SIN_ORDENES" not in item_status_sql:
        conn.execute("DROP TABLE item_status")
    elif item_status_sql is not None:
        if not _column_exists(conn, "item_status", "avg_daily_volume_7d"):
            conn.execute("ALTER TABLE item_status ADD COLUMN avg_daily_volume_7d REAL NOT NULL DEFAULT 0")
        if not _column_exists(conn, "item_status", "avg_daily_order_count_7d"):
            conn.execute(
                "ALTER TABLE item_status ADD COLUMN avg_daily_order_count_7d REAL NOT NULL DEFAULT 0"
            )
        if not _column_exists(conn, "item_status", "best_buy"):
            conn.execute("ALTER TABLE item_status ADD COLUMN best_buy REAL NOT NULL DEFAULT 0")
        if not _column_exists(conn, "item_status", "best_sell"):
            conn.execute("ALTER TABLE item_status ADD COLUMN best_sell REAL NOT NULL DEFAULT 0")

    if _table_sql(conn, "character_order") is not None:
        if not _column_exists(conn, "character_order", "orders_ahead"):
            conn.execute("ALTER TABLE character_order ADD COLUMN orders_ahead INTEGER NOT NULL DEFAULT 0")
        if not _column_exists(conn, "character_order", "price_gap"):
            conn.execute("ALTER TABLE character_order ADD COLUMN price_gap REAL NOT NULL DEFAULT 0")
        if not _column_exists(conn, "character_order", "best_price"):
            conn.execute("ALTER TABLE character_order ADD COLUMN best_price REAL")

    conn.commit()


def _split_statements(script: str) -> list[str]:
    """Separa un script SQL en sentencias completas (executescript haría COMMIT y rompería la
    atomicidad de la migración)."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement and not all(part.strip().startswith("--") or not part.strip()
                                     for part in statement.splitlines()):
                statements.append(statement)
            buffer = ""
    return statements


def _needs_multimarket_migration(conn: sqlite3.Connection) -> bool:
    return any(
        _table_sql(conn, table) is not None and not _column_exists(conn, table, "market_id")
        for table in MULTIMARKET_TABLES
    )


def _migrate_to_multimarket(conn: sqlite3.Connection) -> None:
    """Pasa las cinco tablas por mercado del esquema de un solo mercado al normalizado (market_id
    en la clave). SQLite no deja cambiar una clave primaria con ALTER: las tablas viejas se
    renombran a *_pre_market, se crean las nuevas y se copia todo con market_id = 'jita'.
    Es atómica (el DDL de SQLite es transaccional): si algo falla, o los conteos no coinciden,
    se revierte y la base queda como estaba. Las tablas *_pre_market se conservan hasta que
    alguien las borre a mano con drop_pre_market_tables() tras verificar."""
    if not _needs_multimarket_migration(conn):
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        legacy = [t for t in MULTIMARKET_TABLES
                  if _table_sql(conn, t) is not None and not _column_exists(conn, t, "market_id")]
        for index in ("idx_history_type", "idx_snapshot_type", "idx_opportunity_type", "idx_status_history_type"):
            conn.execute(f"DROP INDEX IF EXISTS {index}")
        for table in legacy:
            conn.execute(f"ALTER TABLE {table} RENAME TO {table}{PRE_MARKET_SUFFIX}")
        for statement in _split_statements(SCHEMA_PATH.read_text(encoding="utf-8")):
            conn.execute(statement)
        _seed_markets(conn)

        copies = {
            "market_history": (
                "market_id, type_id, date, avg_price, highest, lowest, volume, order_count",
                "'jita', type_id, date, avg_price, highest, lowest, volume, order_count"),
            "market_snapshot": (
                "market_id, type_id, captured_at, best_buy, best_sell, buy_volume, sell_volume, "
                "buy_order_count, sell_order_count",
                "'jita', type_id, captured_at, best_buy, best_sell, buy_volume, sell_volume, "
                "buy_order_count, sell_order_count"),
            "item_status": (
                "market_id, type_id, status, reason, spread_bruto, evaluacion_spread, liquidez, roi, "
                "best_buy, best_sell, volumen_diario_real, buy_order_count, sell_order_count, "
                "avg_daily_volume_7d, avg_daily_order_count_7d, last_evaluated_at",
                "'jita', type_id, status, reason, spread_bruto, evaluacion_spread, liquidez, roi, "
                "best_buy, best_sell, volumen_diario_real, buy_order_count, sell_order_count, "
                "avg_daily_volume_7d, avg_daily_order_count_7d, last_evaluated_at"),
            "item_status_history": (
                "id, market_id, type_id, previous_status, new_status, changed_at, reason",
                "id, 'jita', type_id, previous_status, new_status, changed_at, reason"),
            "opportunity_log": (
                "id, market_id, type_id, evaluated_at, buy, sell, volumen_deseado, volumen_diario_real, "
                "beneficio, spread_bruto, precio_min_venta, roi, evaluacion_spread, posicion_vs_volumen, "
                "liquidez, recomendacion",
                "id, 'jita', type_id, evaluated_at, buy, sell, volumen_deseado, volumen_diario_real, "
                "beneficio, spread_bruto, precio_min_venta, roi, evaluacion_spread, posicion_vs_volumen, "
                "liquidez, recomendacion"),
        }
        for table in legacy:
            target, source = copies[table]
            conn.execute(
                f"INSERT INTO {table} ({target}) SELECT {source} FROM {table}{PRE_MARKET_SUFFIX}"
            )
            old = conn.execute(f"SELECT COUNT(*) FROM {table}{PRE_MARKET_SUFFIX}").fetchone()[0]
            new = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if old != new:
                raise RuntimeError(f"Migración multi-mercado: {table} tenía {old} filas y quedó con {new}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def pre_market_tables(conn: sqlite3.Connection) -> list[str]:
    return [t for t in MULTIMARKET_TABLES if _table_sql(conn, t + PRE_MARKET_SUFFIX) is not None]


def drop_pre_market_tables(conn: sqlite3.Connection) -> list[str]:
    """Borra las copias *_pre_market que deja la migración (hacerlo solo tras verificar los datos).
    Devuelve las tablas borradas. Después conviene un VACUUM para devolver el espacio al disco."""
    dropped = pre_market_tables(conn)
    for table in dropped:
        conn.execute(f"DROP TABLE {table}{PRE_MARKET_SUFFIX}")
    conn.commit()
    return dropped


def _seed_markets(conn: sqlite3.Connection) -> None:
    """Siembra los mercados la primera vez; después solo refresca nombre/región/sistema/orden y
    NO toca `enabled` (lo decide quien opera el sistema)."""
    for market_id, name, region_id, system_id, sort_order, enabled in MARKETS_SEED:
        conn.execute(
            "INSERT OR IGNORE INTO market (market_id, name, region_id, system_id, kind, enabled, sort_order) "
            "VALUES (?, ?, ?, ?, 'region', ?, ?)",
            (market_id, name, region_id, system_id, enabled, sort_order),
        )
        conn.execute(
            "UPDATE market SET name = ?, region_id = ?, system_id = ?, sort_order = ? WHERE market_id = ?",
            (name, region_id, system_id, sort_order, market_id),
        )


def _migrate_classification_settings(conn: sqlite3.Connection) -> None:
    """Una sola vez: si existe la vieja tabla classification_settings (T6, fila única
    con solo 2 parámetros), traspasa sus valores a app_settings antes de que
    _seed_defaults() los siembre con el default del registro — así una edición previa
    del usuario no se pierde al migrar al sistema genérico — y la borra."""
    if _table_sql(conn, "classification_settings") is None:
        return
    row = conn.execute(
        "SELECT min_daily_volume_7d, min_daily_order_count_7d FROM classification_settings WHERE id = 1"
    ).fetchone()
    if row is not None:
        for key in ("min_daily_volume_7d", "min_daily_order_count_7d"):
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, category, label, description, value, "
                "default_value, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (key, "Clasificación", key, key, row[key],
                 next(s.default_value for s in SETTINGS if s.key == key)),
            )
    conn.execute("DROP TABLE classification_settings")


def _seed_defaults(conn: sqlite3.Connection) -> None:
    """Siembra cada parámetro del registro (storage/settings_registry.py) la primera
    vez; ediciones posteriores vía update_app_setting() no se pisan en corridas
    futuras (INSERT OR IGNORE). También refresca category/label/description por si el
    registro cambió desde la última corrida (el value/default_value del usuario NO se
    toca acá)."""
    for s in SETTINGS:
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, category, label, description, value, "
            "default_value, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (s.key, s.category, s.label, s.description, s.default_value, s.default_value),
        )
        conn.execute(
            "UPDATE app_settings SET category = ?, label = ?, description = ?, default_value = ? "
            "WHERE key = ?",
            (s.category, s.label, s.description, s.default_value, s.key),
        )


NOTIFICATION_OUTBOX_SCHEMA = """
-- Avisos de Telegram que no se pudieron enviar (notifications/outbox.py): se reintentan en las
-- corridas siguientes de los motores.
CREATE TABLE IF NOT EXISTS notification_outbox (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    context     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    claimed_at  TEXT,
    last_error  TEXT
);
"""

ANALYTICS_SCHEMA = """
-- Métricas de uso con consentimiento (backend/api/analytics.py): sin IP ni user agent.
CREATE TABLE IF NOT EXISTS analytics_visitor (
    visitor_id   TEXT PRIMARY KEY,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    visit_count  INTEGER NOT NULL DEFAULT 1,
    lang         TEXT
);
CREATE TABLE IF NOT EXISTS analytics_visit (
    visit_id        TEXT PRIMARY KEY,
    visitor_id      TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    last_ping_at    TEXT NOT NULL,
    active_seconds  INTEGER NOT NULL DEFAULT 0,
    pageviews       INTEGER NOT NULL DEFAULT 1,
    landing_path    TEXT,
    ref_host        TEXT
);
CREATE INDEX IF NOT EXISTS idx_analytics_visit_visitor ON analytics_visit(visitor_id);
CREATE INDEX IF NOT EXISTS idx_analytics_visit_started ON analytics_visit(started_at);
"""


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        # WAL: los lectores (la API) no se bloquean mientras un motor escribe -- en el modo
        # por defecto un commit grande del motor de mercado dejaba a la API con "database is
        # locked" (500). Es persistente en el archivo; si otro proceso tiene la base
        # abierta no se puede cambiar de modo y simplemente se reintenta en la próxima corrida.
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    try:
        _migrate_schema(conn)
        _migrate_to_multimarket(conn)
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _seed_markets(conn)
        conn.executescript(ANALYTICS_SCHEMA)
        conn.executescript(NOTIFICATION_OUTBOX_SCHEMA)
        _migrate_classification_settings(conn)
        _seed_defaults(conn)
        conn.commit()
    finally:
        conn.close()


def upsert_item_type(conn: sqlite3.Connection, type_id: int, name: str) -> None:
    conn.execute(
        "INSERT INTO item_type (type_id, name) VALUES (?, ?) "
        "ON CONFLICT(type_id) DO UPDATE SET name = excluded.name",
        (type_id, name),
    )


def upsert_market_history(conn: sqlite3.Connection, type_id: int, row: dict,
                          market_id: str = DEFAULT_MARKET) -> None:
    conn.execute(
        """
        INSERT INTO market_history
            (market_id, type_id, date, avg_price, highest, lowest, volume, order_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_id, type_id, date) DO UPDATE SET
            avg_price = excluded.avg_price,
            highest = excluded.highest,
            lowest = excluded.lowest,
            volume = excluded.volume,
            order_count = excluded.order_count
        """,
        (
            market_id,
            type_id,
            row["date"],
            row["average"],
            row["highest"],
            row["lowest"],
            row["volume"],
            row["order_count"],
        ),
    )


def upsert_market_snapshot(conn: sqlite3.Connection, type_id: int, captured_at: str, row: dict,
                           market_id: str = DEFAULT_MARKET) -> None:
    conn.execute(
        """
        INSERT INTO market_snapshot
            (market_id, type_id, captured_at, best_buy, best_sell, buy_volume, sell_volume,
             buy_order_count, sell_order_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_id, type_id, captured_at) DO UPDATE SET
            best_buy = excluded.best_buy,
            best_sell = excluded.best_sell,
            buy_volume = excluded.buy_volume,
            sell_volume = excluded.sell_volume,
            buy_order_count = excluded.buy_order_count,
            sell_order_count = excluded.sell_order_count
        """,
        (
            market_id,
            type_id,
            captured_at,
            row.get("best_buy"),
            row.get("best_sell"),
            row.get("buy_volume"),
            row.get("sell_volume"),
            row.get("buy_order_count", 0),
            row.get("sell_order_count", 0),
        ),
    )


def prune_old_snapshots(conn: sqlite3.Connection, keep_days: float | None = None,
                        batch_size: int = 20000, keep_hours: float | None = None,
                        market_id: str = DEFAULT_MARKET) -> int:
    """Borra snapshots de órdenes más viejos que `keep_hours` horas (o `keep_days` días): solo
    el último de cada ítem alimenta al screening y a la API; el resto es historial que crecía
    sin límite -- 1,3 GB en la VM de 1 GB de RAM.

    Borra ítem por ítem con `type_id = ? AND datetime(captured_at) < datetime(?)`: la PK (type_id,
    captured_at) resuelve el ítem y `datetime()` compara bien aunque los formatos de fecha difieran
    (con "T" o con espacio). Un `WHERE captured_at < ?` solo (la columna no está al frente de la PK)
    recorre toda la tabla cada vez, y con un ciclo cada pocos minutos eso pesa; un único
    DELETE gigante dejó antes a la API tirando "database is locked" en producción. Los ítems
    se procesan en lotes de `batch_size`, un commit por lote, para no mantener un lock de
    escritura largo sobre la SQLite compartida con la API.
    No hace VACUUM: las páginas liberadas se reutilizan. Devuelve las filas borradas."""
    if keep_hours is None:
        if keep_days is None:
            raise ValueError("indicá keep_hours o keep_days")
        keep_hours = keep_days * 24
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=keep_hours)).isoformat()
    type_ids = [row[0] for row in conn.execute(
        "SELECT DISTINCT type_id FROM market_snapshot WHERE market_id = ?", (market_id,))]
    deleted = 0
    for start in range(0, len(type_ids), batch_size):
        batch = type_ids[start:start + batch_size]
        deleted += conn.executemany(
            "DELETE FROM market_snapshot WHERE market_id = ? AND type_id = ? "
            "AND datetime(captured_at) < datetime(?)",
            [(market_id, type_id, cutoff) for type_id in batch],
        ).rowcount
        conn.commit()
    return deleted


def get_item_status(conn: sqlite3.Connection, type_id: int,
                    market_id: str = DEFAULT_MARKET) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM item_status WHERE market_id = ? AND type_id = ?", (market_id, type_id)
    ).fetchone()


def upsert_item_status(conn: sqlite3.Connection, row: dict, market_id: str = DEFAULT_MARKET) -> None:
    conn.execute(
        """
        INSERT INTO item_status
            (market_id, type_id, status, reason, spread_bruto, evaluacion_spread, liquidez, roi,
             best_buy, best_sell, volumen_diario_real, buy_order_count, sell_order_count,
             avg_daily_volume_7d, avg_daily_order_count_7d, last_evaluated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_id, type_id) DO UPDATE SET
            status = excluded.status,
            reason = excluded.reason,
            spread_bruto = excluded.spread_bruto,
            evaluacion_spread = excluded.evaluacion_spread,
            liquidez = excluded.liquidez,
            roi = excluded.roi,
            best_buy = excluded.best_buy,
            best_sell = excluded.best_sell,
            volumen_diario_real = excluded.volumen_diario_real,
            buy_order_count = excluded.buy_order_count,
            sell_order_count = excluded.sell_order_count,
            avg_daily_volume_7d = excluded.avg_daily_volume_7d,
            avg_daily_order_count_7d = excluded.avg_daily_order_count_7d,
            last_evaluated_at = excluded.last_evaluated_at
        """,
        (
            market_id, row["type_id"], row["status"], row["reason"], row["spread_bruto"],
            row["evaluacion_spread"], row["liquidez"], row["roi"],
            row["best_buy"], row["best_sell"],
            row["volumen_diario_real"], row["buy_order_count"], row["sell_order_count"],
            row["avg_daily_volume_7d"], row["avg_daily_order_count_7d"],
            row["last_evaluated_at"],
        ),
    )


def upsert_item_category(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO item_category (type_id, group_id, group_name, category_id, category_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(type_id) DO UPDATE SET
            group_id = excluded.group_id,
            group_name = excluded.group_name,
            category_id = excluded.category_id,
            category_name = excluded.category_name
        """,
        (row["type_id"], row["group_id"], row["group_name"], row["category_id"], row["category_name"]),
    )


def get_cached_category_type_ids(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT type_id FROM item_category").fetchall()
    return {r["type_id"] for r in rows}


def get_cached_group(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT group_id, group_name, category_id, category_name FROM item_category "
        "WHERE group_id = ? LIMIT 1",
        (group_id,),
    ).fetchone()


def insert_status_history(conn: sqlite3.Connection, type_id: int, previous_status: str | None,
                           new_status: str, changed_at: str, reason: str,
                           market_id: str = DEFAULT_MARKET) -> None:
    conn.execute(
        """
        INSERT INTO item_status_history (market_id, type_id, previous_status, new_status, changed_at, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (market_id, type_id, previous_status, new_status, changed_at, reason),
    )


def get_active_character_order_ids(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT order_id FROM character_order").fetchall()
    return {r["order_id"] for r in rows}


def get_character_order(conn: sqlite3.Connection, order_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM character_order WHERE order_id = ?", (order_id,)).fetchone()


def upsert_character_order(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO character_order
            (order_id, type_id, region_id, is_buy_order, price, volume_remain, volume_total,
             issued, is_undercut, undercut_alerted, orders_ahead, price_gap, best_price,
             first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            price = excluded.price,
            volume_remain = excluded.volume_remain,
            is_undercut = excluded.is_undercut,
            undercut_alerted = excluded.undercut_alerted,
            orders_ahead = excluded.orders_ahead,
            price_gap = excluded.price_gap,
            best_price = excluded.best_price,
            last_seen_at = excluded.last_seen_at
        """,
        (
            row["order_id"], row["type_id"], row["region_id"], int(row["is_buy_order"]),
            row["price"], row["volume_remain"], row["volume_total"], row["issued"],
            int(row["is_undercut"]), int(row["is_undercut"]),
            row["orders_ahead"], row["price_gap"], row["best_price"],
            row["first_seen_at"], row["last_seen_at"],
        ),
    )


def delete_character_order(conn: sqlite3.Connection, order_id: int) -> None:
    conn.execute("DELETE FROM character_order WHERE order_id = ?", (order_id,))


def insert_character_order_closed(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO character_order_closed
            (order_id, type_id, is_buy_order, price, final_state, closed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row["order_id"], row["type_id"], int(row["is_buy_order"]), row["price"],
            row["final_state"], row["closed_at"],
        ),
    )


def insert_character_order_fill(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """
        INSERT INTO character_order_fill
            (order_id, type_id, is_buy_order, price, filled_units, volume_remain, filled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["order_id"], row["type_id"], int(row["is_buy_order"]), row["price"],
            row["filled_units"], row["volume_remain"], row["filled_at"],
        ),
    )


def _first_opportunity_id_since(conn: sqlite3.Connection, since_iso: str) -> int | None:
    """Primer `id` de opportunity_log con evaluated_at >= since_iso, o None si no hay ninguno.
    evaluated_at crece con el id (el log solo se anexa), así que se busca por bisección sobre la
    clave primaria: no hace falta un índice nuevo sobre una tabla de millones de filas."""
    bounds = conn.execute("SELECT MIN(id), MAX(id) FROM opportunity_log").fetchone()
    lo, hi = bounds[0], bounds[1]
    if lo is None:
        return None

    def satisfied(first_id: int) -> bool:
        row = conn.execute(
            "SELECT evaluated_at FROM opportunity_log WHERE id >= ? ORDER BY id LIMIT 1", (first_id,),
        ).fetchone()
        return row is not None and row[0] >= since_iso

    if not satisfied(hi):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if satisfied(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def recent_opportunity_times(conn: sqlite3.Connection, since_iso: str,
                             market_id: str = DEFAULT_MARKET) -> dict[int, str]:
    """Último evaluated_at registrado por ítem desde `since_iso` (para no registrar un ítem
    más de una vez por intervalo)."""
    first = _first_opportunity_id_since(conn, since_iso)
    if first is None:
        return {}
    rows = conn.execute(
        "SELECT type_id, MAX(evaluated_at) FROM opportunity_log WHERE id >= ? AND market_id = ? "
        "GROUP BY type_id", (first, market_id),
    )
    return {row[0]: row[1] for row in rows}


def purge_opportunity_log(conn: sqlite3.Connection, keep_days: float, batch_size: int = 20000,
                          max_batches: int = 10) -> int:
    """Borra del log las filas más viejas que `keep_days` días, por rangos de id (sin índice
    nuevo), en lotes con un commit por lote para no retener el lock de escritura. `max_batches`
    acota el trabajo de cada ciclo: una acumulación grande se elimina en varios ciclos. Devuelve
    las filas borradas."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    first_keep = _first_opportunity_id_since(conn, cutoff)
    if first_keep is None:
        top = conn.execute("SELECT MAX(id) FROM opportunity_log").fetchone()[0]
        if top is None:
            return 0
        first_keep = top + 1
    deleted = 0
    for _ in range(max_batches):
        lowest = conn.execute("SELECT MIN(id) FROM opportunity_log").fetchone()[0]
        if lowest is None or lowest >= first_keep:
            break
        upper = min(lowest + batch_size, first_keep)
        deleted += conn.execute(
            "DELETE FROM opportunity_log WHERE id >= ? AND id < ?", (lowest, upper),
        ).rowcount
        conn.commit()
    return deleted


def insert_opportunity(conn: sqlite3.Connection, row: dict, market_id: str = DEFAULT_MARKET) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_log
            (market_id, type_id, evaluated_at, buy, sell, volumen_deseado, volumen_diario_real,
             beneficio, spread_bruto, precio_min_venta, roi, evaluacion_spread,
             posicion_vs_volumen, liquidez, recomendacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            market_id,
            row["type_id"],
            row["evaluated_at"],
            row["buy"],
            row["sell"],
            row["volumen_deseado"],
            row["volumen_diario_real"],
            row["beneficio"],
            row["spread_bruto"],
            row["precio_min_venta"],
            row["roi"],
            row["evaluacion_spread"],
            row["posicion_vs_volumen"],
            row["liquidez"],
            row["recomendacion"],
        ),
    )


def get_app_settings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Todos los parámetros configurables (storage/settings_registry.py), sembrados
    por _seed_defaults(). Ordenados por categoría/clave para que la PWA los agrupe
    consistentemente sin tener que ordenar del lado del cliente."""
    return conn.execute("SELECT * FROM app_settings ORDER BY category, key").fetchall()


def get_app_settings_dict(conn: sqlite3.Connection) -> dict[str, float]:
    """key -> value actual, para que los motores armen EveCalculatorConfig/SanityConfig
    con **kwargs filtrados en vez de mapear cada campo a mano."""
    return {r["key"]: r["value"] for r in get_app_settings(conn)}


def update_app_setting(conn: sqlite3.Connection, key: str, value: float) -> None:
    cur = conn.execute(
        "UPDATE app_settings SET value = ?, updated_at = datetime('now') WHERE key = ?",
        (value, key),
    )
    if cur.rowcount == 0:
        raise KeyError(f"No existe el parámetro '{key}'")
    conn.commit()


def reset_app_settings(conn: sqlite3.Connection, keys: list[str] | None = None) -> None:
    """Restablece a default_value. `keys=None` resetea TODOS los parámetros (botón
    "Restablecer valores por defecto" de Ajustes); con una lista, solo esos."""
    if keys is None:
        conn.execute("UPDATE app_settings SET value = default_value, updated_at = datetime('now')")
    else:
        conn.executemany(
            "UPDATE app_settings SET value = default_value, updated_at = datetime('now') WHERE key = ?",
            [(k,) for k in keys],
        )
    conn.commit()
