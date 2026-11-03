"""Repositorio de historial de analisis (CA-16)."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from infrastructure.database import get_connection


def save_analysis(item: str, input_dict: Dict[str, Any], result_dict: Dict[str, Any]) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses (
                created_at, item, buy_price, sell_price,
                eve_hub_profit_unit, eve_hub_margin_pct, volume_day, trend_pct, volatility_pct, eve_hub_profit_day,
                calc_net_profit_unit, calc_net_margin_pct, calc_roi_pct,
                recommended_units, capital_used, score, recommendation_status, recommendation_label,
                input_json, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                item,
                result_dict["buy_price"],
                result_dict["sell_price"],
                result_dict["eve_hub_profit_unit"],
                result_dict["eve_hub_margin_pct"],
                result_dict["volume_day"],
                result_dict["trend_pct"],
                result_dict["volatility_pct"],
                result_dict["eve_hub_profit_day"],
                result_dict["calc_net_profit_unit"],
                result_dict["calc_net_margin_pct"],
                result_dict["calc_roi_pct"],
                result_dict["recommended_units"],
                result_dict["capital_used"],
                result_dict["score"],
                result_dict["recommendation_status"],
                result_dict["recommendation_label"],
                json.dumps(input_dict, ensure_ascii=False, default=str),
                json.dumps(result_dict, ensure_ascii=False, default=str),
            ),
        )
        return cur.lastrowid


def list_analyses(limit: int = 200) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_analysis(analysis_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        return dict(row) if row else None
