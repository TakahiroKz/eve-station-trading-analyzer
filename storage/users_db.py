"""Base de usuarios (users.db): SQLite aparte de market.db (otro archivo, otras copias, otro radio de daño).

Guarda lo mínimo: personaje, consentimiento, refresh token CIFRADO y sesiones (de estas solo el hash).
Ver docs/ANALISIS_CUENTAS_Y_BASE_DE_DATOS.md.
"""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1
SESSION_TTL_DAYS = 30
INACTIVE_MONTHS = 12
_SLIDE_EVERY = timedelta(hours=1)   # la sesión se prolonga como mucho una vez por hora (evita una escritura por petición)

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    character_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    consent_version TEXT NOT NULL,
    consent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_token (
    character_id INTEGER PRIMARY KEY REFERENCES user(character_id) ON DELETE CASCADE,
    refresh_token_enc BLOB NOT NULL,
    scopes TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'REVOKED')),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_session (
    token_hash TEXT PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES user(character_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_session_char ON user_session(character_id);
CREATE INDEX IF NOT EXISTS idx_user_session_exp ON user_session(expires_at);
"""


def users_db_path() -> str:
    explicit = os.environ.get("USERS_DB_PATH")
    if explicit:
        return explicit
    return str(Path(os.environ.get("DB_PATH", "./storage/market.db")).parent / "users.db")


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or users_db_path()
    new_file = not Path(path).exists()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    if new_file:
        try:
            os.chmod(path, 0o600)   # contiene tokens (cifrados) y datos personales: solo el dueño
        except OSError:
            pass
    return conn


def init_users_db(path: str | None = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upsert_user(conn: sqlite3.Connection, character_id: int, name: str, consent_version: str, now: datetime) -> None:
    stamp = iso(now)
    conn.execute(
        "INSERT INTO user (character_id, name, created_at, last_seen_at, consent_version, consent_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(character_id) DO UPDATE SET name = excluded.name, "
        "last_seen_at = excluded.last_seen_at, consent_version = excluded.consent_version, "
        "consent_at = excluded.consent_at", (character_id, name, stamp, stamp, consent_version, stamp))


def save_token(conn: sqlite3.Connection, character_id: int, encrypted: bytes, scopes: str, now: datetime) -> None:
    conn.execute(
        "INSERT INTO user_token (character_id, refresh_token_enc, scopes, status, updated_at) VALUES (?, ?, ?, 'ACTIVE', ?) "
        "ON CONFLICT(character_id) DO UPDATE SET refresh_token_enc = excluded.refresh_token_enc, "
        "scopes = excluded.scopes, status = 'ACTIVE', updated_at = excluded.updated_at",
        (character_id, encrypted, scopes, iso(now)))


def create_session(conn: sqlite3.Connection, character_id: int, now: datetime) -> str:
    """Devuelve el token en claro (va solo a la cookie); en la base queda su hash."""
    raw = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO user_session (token_hash, character_id, created_at, expires_at, last_seen_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (_hash(raw), character_id, iso(now), iso(now + timedelta(days=SESSION_TTL_DAYS)), iso(now)))
    return raw


def get_session_user(conn: sqlite3.Connection, raw: str | None, now: datetime) -> sqlite3.Row | None:
    if not raw or len(raw) > 200:
        return None
    row = conn.execute(
        "SELECT u.character_id, u.name, u.consent_version, s.last_seen_at AS session_seen "
        "FROM user_session s JOIN user u ON u.character_id = s.character_id "
        "WHERE s.token_hash = ? AND s.expires_at > ?", (_hash(raw), iso(now))).fetchone()
    if row is None:
        return None
    seen = datetime.strptime(row["session_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if now - seen >= _SLIDE_EVERY:
        conn.execute("UPDATE user_session SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                     (iso(now), iso(now + timedelta(days=SESSION_TTL_DAYS)), _hash(raw)))
        conn.execute("UPDATE user SET last_seen_at = ? WHERE character_id = ?", (iso(now), row["character_id"]))
        conn.commit()
    return row


def delete_session(conn: sqlite3.Connection, raw: str | None) -> None:
    if raw:
        conn.execute("DELETE FROM user_session WHERE token_hash = ?", (_hash(raw),))


def delete_token(conn: sqlite3.Connection, character_id: int) -> None:
    conn.execute("DELETE FROM user_token WHERE character_id = ?", (character_id,))


def delete_user(conn: sqlite3.Connection, character_id: int) -> None:
    """Borra todo lo del personaje (token y sesiones caen en cascada)."""
    conn.execute("DELETE FROM user WHERE character_id = ?", (character_id,))


def purge_expired_sessions(conn: sqlite3.Connection, now: datetime) -> int:
    cur = conn.execute("DELETE FROM user_session WHERE expires_at <= ?", (iso(now),))
    return cur.rowcount


def purge_inactive_users(conn: sqlite3.Connection, now: datetime, months: int = INACTIVE_MONTHS) -> int:
    cutoff = iso(now - timedelta(days=30 * months))
    cur = conn.execute("DELETE FROM user WHERE last_seen_at < ?", (cutoff,))
    return cur.rowcount


def export_user(conn: sqlite3.Connection, character_id: int) -> dict | None:
    """Todo lo que se guarda de la persona, salvo el token (que es un secreto, no un dato suyo que pueda leerse)."""
    user = conn.execute("SELECT * FROM user WHERE character_id = ?", (character_id,)).fetchone()
    if user is None:
        return None
    token = conn.execute("SELECT scopes, status, updated_at FROM user_token WHERE character_id = ?",
                         (character_id,)).fetchone()
    sessions = conn.execute("SELECT created_at, expires_at, last_seen_at FROM user_session WHERE character_id = ?",
                            (character_id,)).fetchall()
    return {"user": dict(user), "token": dict(token) if token else None, "sessions": [dict(s) for s in sessions]}
