"""Conexion y esquema SQLite. Persistencia local, sin dependencias externas (CA-16, CA-17)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from infrastructure.paths import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    item TEXT NOT NULL,
    buy_price REAL NOT NULL,
    sell_price REAL NOT NULL,
    eve_hub_profit_unit REAL,
    eve_hub_margin_pct REAL,
    volume_day REAL,
    trend_pct REAL,
    volatility_pct REAL,
    eve_hub_profit_day REAL,
    calc_net_profit_unit REAL,
    calc_net_margin_pct REAL,
    calc_roi_pct REAL,
    recommended_units INTEGER,
    capital_used REAL,
    score REAL,
    recommendation_status TEXT,
    recommendation_label TEXT,
    input_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER,
    created_at TEXT NOT NULL,
    item TEXT NOT NULL,
    units_bought INTEGER NOT NULL,
    real_buy_price REAL NOT NULL,
    real_sell_price REAL,
    hours_to_sell REAL,
    real_profit REAL,
    notes TEXT,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id)
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
