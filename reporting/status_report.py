"""Muestra el scope vigente de ítems: POTENCIAL / POTENCIAL_SIN_ORDENES / DESCARTADO / EN_OBSERVACION.

Uso:
    python -m reporting.status_report            # resumen por conteo
    python -m reporting.status_report --detail POTENCIAL   # lista completa de una categoría
    (ordenada por volumen diario real primero, ROI como criterio secundario)
"""
import argparse
import os
import sys

import pandas as pd
from dotenv import load_dotenv

from storage.db import get_connection


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--detail", choices=["POTENCIAL", "POTENCIAL_SIN_ORDENES", "DESCARTADO", "EN_OBSERVACION"],
        default=None,
        help="Lista completa de ítems en esa categoría (por defecto solo muestra el resumen)",
    )
    args = parser.parse_args()

    db_path = os.environ.get("DB_PATH", "./storage/market.db")
    conn = get_connection(db_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT s.status, s.reason, s.spread_bruto, s.evaluacion_spread, s.liquidez,
                   s.roi, s.volumen_diario_real, s.buy_order_count, s.sell_order_count,
                   s.avg_daily_volume_7d, s.avg_daily_order_count_7d,
                   s.last_evaluated_at, i.name
            FROM item_status s
            JOIN item_type i ON i.type_id = s.type_id
            """,
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        print("Sin clasificaciones todavía — corre scheduler/run.py primero.")
        return 0

    if args.detail:
        subset = df[df["status"] == args.detail].sort_values(
            ["volumen_diario_real", "roi"], ascending=[False, False],
        )
        cols = ["name", "volumen_diario_real", "roi", "spread_bruto", "evaluacion_spread",
                "liquidez", "avg_daily_volume_7d", "avg_daily_order_count_7d"]
        print(subset[cols].to_string(index=False))
    else:
        print(df["status"].value_counts().to_string())
        print(f"\nTotal clasificados: {len(df)} (última corrida: {df['last_evaluated_at'].max()})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
