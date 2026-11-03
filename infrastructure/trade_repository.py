"""Repositorio del diario de operaciones reales (CA-17, CA-18)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from infrastructure.database import get_connection


def save_trade(
    item: str,
    units_bought: int,
    real_buy_price: float,
    analysis_id: Optional[int] = None,
    real_sell_price: Optional[float] = None,
    hours_to_sell: Optional[float] = None,
    real_profit: Optional[float] = None,
    notes: str = "",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades (
                analysis_id, created_at, item, units_bought, real_buy_price,
                real_sell_price, hours_to_sell, real_profit, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                datetime.now().isoformat(timespec="seconds"),
                item,
                units_bought,
                real_buy_price,
                real_sell_price,
                hours_to_sell,
                real_profit,
                notes,
            ),
        )
        return cur.lastrowid


def list_trades(limit: int = 200) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def compare_prediction_vs_actual(analysis_id: int) -> Optional[Dict[str, Any]]:
    """CA-18: compara la recomendacion del analisis contra el resultado real registrado."""
    with get_connection() as conn:
        analysis = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        trades = conn.execute(
            "SELECT * FROM trades WHERE analysis_id = ? ORDER BY id", (analysis_id,)
        ).fetchall()
        if not analysis:
            return None
        return {
            "analysis": dict(analysis),
            "trades": [dict(t) for t in trades],
        }
