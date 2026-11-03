"""Motor Analizador de Mercado: ingesta ESI -> SQLite -> analítica -> screening
EveCalculator -> reporting. Corre cada 4 horas (ver scripts/setup_task_scheduler.ps1).

No toca tus órdenes de personaje — eso lo hace el motor de posiciones
(scheduler/orders_run.py), separado y con una cadencia mucho más ágil (cada 5 min).
Ambos motores comparten el mismo componente de notificación (notifications/telegram_bot.py).

Uso:
    python -m scheduler.run --backfill      # primera ejecución: histórico completo
    python -m scheduler.run                 # ejecución periódica (snapshot + history del día)
"""
import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx
import pandas as pd
from dotenv import load_dotenv

from analytics.classification import classify
from analytics.eve_calculator import (
    EveCalculatorConfig,
    config_from_settings,
    evaluar_oportunidad,
    resolve_volumen_deseado,
)
from analytics.market_aggregation import build_orders_by_type
from analytics.sanity import SanityConfig, is_price_sane
from ingestion.esi_client import DEFAULT_BASE_URL, EsiClient
from ingestion.wallet import get_current_wallet_balance
from reporting.excel_writer import EveCalculatorRegistro
from reporting.gsheets_sync import append_opportunity_row
from notifications.events import NewOpportunity, dispatch
from storage.db import (
    get_app_settings_dict,
    get_cached_category_type_ids,
    get_cached_group,
    get_connection,
    get_item_status,
    init_db,
    insert_opportunity,
    insert_status_history,
    upsert_item_category,
    upsert_item_status,
    upsert_item_type,
    upsert_market_history,
    upsert_market_snapshot,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # una línea por request satura el log en corridas programadas
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def ingest(client: EsiClient, region_id: int, db_path: str, backfill: bool, max_workers: int = 20) -> list[int]:
    conn = get_connection(db_path)
    captured_at = datetime.now(timezone.utc).isoformat()

    try:
        type_ids = client.get_active_type_ids(region_id)
        logger.info("Tipos activos en la región %s: %d", region_id, len(type_ids))

        orders = client.get_orders(region_id)
        orders_by_type = build_orders_by_type(orders)

        names = client.get_type_names_bulk(type_ids)
        for type_id in type_ids:
            upsert_item_type(conn, type_id, names.get(type_id, f"type_{type_id}"))
            snapshot = orders_by_type.get(type_id, {})
            upsert_market_snapshot(conn, type_id, captured_at, snapshot)
        conn.commit()
        logger.info("Nombres e snapshot de órdenes cargados para %d tipos", len(type_ids))

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(client.get_history, region_id, type_id): type_id for type_id in type_ids}
            for future in as_completed(futures):
                type_id = futures[future]
                try:
                    history = future.result()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        # 404 es esperado (ítem nunca transado en esta región); cualquier otro
                        # código sí es un fallo real digno de traceback.
                        logger.exception("Fallo al traer histórico de type_id=%s", type_id)
                    history = []
                except Exception:
                    logger.exception("Fallo al traer histórico de type_id=%s", type_id)
                    history = []

                if backfill:
                    for row in history:
                        upsert_market_history(conn, type_id, row)
                elif history:
                    upsert_market_history(conn, type_id, history[-1])

                done += 1
                if done % 100 == 0:
                    conn.commit()
                    logger.info("Histórico procesado: %d/%d", done, len(type_ids))

        conn.commit()
        logger.info("Ingesta completada para %d tipos", len(type_ids))
        return type_ids
    finally:
        conn.close()


def ingest_categories(client: EsiClient, db_path: str, type_ids: list[int], max_workers: int = 20) -> None:
    """Cachea categoría/grupo por ítem (T2 del backlog: filtro por categoría).

    Caro solo la primera vez: no hay endpoint bulk para group_id por type_id, así que
    se pide uno por uno para los que todavía faltan en item_category. group_id -> grupo
    -> categoría sí se resuelve una sola vez por grupo (hay unos pocos cientos, no miles).
    """
    conn = get_connection(db_path)
    try:
        already_cached = get_cached_category_type_ids(conn)
        missing = [t for t in type_ids if t not in already_cached]
        if not missing:
            return
        logger.info("Categorías: %d ítems nuevos sin cachear (de %d totales)", len(missing), len(type_ids))

        group_cache: dict[int, dict] = {}
        category_name_cache: dict[int, str] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(client.get_type_group_id, type_id): type_id for type_id in missing}
            done = 0
            for future in as_completed(futures):
                type_id = futures[future]
                try:
                    group_id = future.result()
                except Exception:
                    logger.exception("Fallo al traer group_id de type_id=%s", type_id)
                    continue

                if group_id not in group_cache:
                    cached_row = get_cached_group(conn, group_id)
                    if cached_row is not None:
                        group_cache[group_id] = dict(cached_row)
                    else:
                        try:
                            group_info = client.get_group(group_id)
                            category_id = group_info["category_id"]
                            if category_id not in category_name_cache:
                                category_name_cache[category_id] = client.get_category_name(category_id)
                            group_cache[group_id] = {
                                "group_id": group_id,
                                "group_name": group_info["name"],
                                "category_id": category_id,
                                "category_name": category_name_cache[category_id],
                            }
                        except Exception:
                            logger.exception("Fallo al traer grupo/categoría para group_id=%s", group_id)
                            continue

                g = group_cache[group_id]
                upsert_item_category(conn, {
                    "type_id": type_id,
                    "group_id": g["group_id"],
                    "group_name": g["group_name"],
                    "category_id": g["category_id"],
                    "category_name": g["category_name"],
                })

                done += 1
                if done % 200 == 0:
                    conn.commit()
                    logger.info("Categorías procesadas: %d/%d", done, len(missing))

        conn.commit()
        logger.info("Categorías cacheadas para %d ítems nuevos", done)
    finally:
        conn.close()


def screen_opportunities(db_path: str, excel_path: str,
                          fallback_volumen_deseado: float | None = None) -> pd.DataFrame:
    conn = get_connection(db_path)
    try:
        settings = get_app_settings_dict(conn)
        eve_config = config_from_settings(EveCalculatorConfig, settings)
        sanity_config = config_from_settings(SanityConfig, settings)
        position_pct = settings["position_size_pct_wallet"]
        fallback = (
            fallback_volumen_deseado if fallback_volumen_deseado is not None
            else settings["volumen_deseado_fallback"]
        )

        wallet_balance = get_current_wallet_balance()
        if wallet_balance is not None:
            logger.info("Wallet ISK: %.2f — posición por ítem = %.0f%% de eso / precio de compra",
                        wallet_balance, position_pct * 100)
        else:
            logger.warning("Sin wallet disponible; usando volumen deseado fijo = %s", fallback)

        logger.info("AlertRules activas: min_daily_volume_7d=%.0f, min_daily_order_count_7d=%.0f",
                    settings["min_daily_volume_7d"], settings["min_daily_order_count_7d"])

        snapshot = pd.read_sql_query(
            "SELECT s.*, i.name FROM market_snapshot s JOIN item_type i ON i.type_id = s.type_id",
            conn,
        )
        history = pd.read_sql_query("SELECT * FROM market_history", conn)

        latest_snapshot = snapshot.sort_values("captured_at").groupby("type_id").tail(1)
        recent_history = history.sort_values("date").groupby("type_id").tail(30)
        recent_volume = recent_history.groupby("type_id")["volume"].mean().rename("volumen_diario_real")
        # Precio de referencia = mediano del histórico reciente (transacciones reales ejecutadas),
        # usado para descartar snapshots de órdenes activas que son basura (ver analytics/sanity.py).
        reference_price = recent_history.groupby("type_id")["avg_price"].median().rename("reference_price")

        # Actividad real de mercado (últimos 7 días de TRANSACCIONES EJECUTADAS, no del libro de
        # órdenes abiertas) — gate de analytics/classification.py contra "una sola ballena".
        recent_history_7d = history.sort_values("date").groupby("type_id").tail(7)
        avg_daily_volume_7d = recent_history_7d.groupby("type_id")["volume"].mean().rename("avg_daily_volume_7d")
        avg_daily_order_count_7d = (
            recent_history_7d.groupby("type_id")["order_count"].mean().rename("avg_daily_order_count_7d")
        )

        merged = latest_snapshot.merge(recent_volume, on="type_id", how="inner")
        merged = merged.merge(reference_price, on="type_id", how="inner")
        merged = merged.merge(avg_daily_volume_7d, on="type_id", how="inner")
        merged = merged.merge(avg_daily_order_count_7d, on="type_id", how="inner")
        merged = merged.dropna(subset=["best_buy", "best_sell"])
        merged = merged[(merged["best_buy"] > 0) & (merged["volumen_diario_real"] > 0)]

        results = []
        events: list = []
        with EveCalculatorRegistro(excel_path) as registro:
            for _, row in merged.iterrows():
                volumen_deseado = resolve_volumen_deseado(
                    row["best_buy"], wallet_balance, position_pct, fallback,
                )
                result = evaluar_oportunidad(
                    item=row["name"],
                    buy=row["best_buy"],
                    sell=row["best_sell"],
                    volumen_deseado=volumen_deseado,
                    volumen_diario_real=row["volumen_diario_real"],
                    config=eve_config,
                )
                results.append((row["type_id"], result))
                now = datetime.now(timezone.utc).isoformat()

                insert_opportunity(conn, {
                    "type_id": row["type_id"],
                    "evaluated_at": now,
                    "buy": result.buy,
                    "sell": result.sell,
                    "volumen_deseado": result.volumen_deseado,
                    "volumen_diario_real": result.volumen_diario_real,
                    "beneficio": result.beneficio,
                    "spread_bruto": result.spread_bruto,
                    "precio_min_venta": result.precio_min_venta,
                    "roi": result.roi,
                    "evaluacion_spread": result.evaluacion_spread,
                    "posicion_vs_volumen": result.posicion_vs_volumen,
                    "liquidez": result.liquidez,
                    "recomendacion": result.recomendacion,
                })

                # Recategorización: todo ítem queda clasificado, sin importar si termina
                # registrado como oportunidad en Excel/Sheets o no.
                buy_order_count = int(row.get("buy_order_count", 0) or 0)
                sell_order_count = int(row.get("sell_order_count", 0) or 0)
                avg_daily_volume_7d = float(row["avg_daily_volume_7d"])
                avg_daily_order_count_7d = float(row["avg_daily_order_count_7d"])

                if is_price_sane(row["best_buy"], row["best_sell"], row["reference_price"], sanity_config):
                    status, reason = classify(
                        result.evaluacion_spread, result.liquidez,
                        avg_daily_volume_7d, avg_daily_order_count_7d,
                        min_daily_volume_7d=settings["min_daily_volume_7d"],
                        min_daily_order_count_7d=settings["min_daily_order_count_7d"],
                    )
                else:
                    status, reason = "DESCARTADO", (
                        f"best_buy/best_sell ({row['best_buy']:.2f}/{row['best_sell']:.2f}) muy alejados "
                        f"del precio histórico reciente ({row['reference_price']:.2f}): probable orden "
                        f"basura, no es una oportunidad real."
                    )
                previous = get_item_status(conn, row["type_id"])
                previous_status = previous["status"] if previous else None

                upsert_item_status(conn, {
                    "type_id": row["type_id"],
                    "status": status,
                    "reason": reason,
                    "spread_bruto": result.spread_bruto,
                    "evaluacion_spread": result.evaluacion_spread,
                    "liquidez": result.liquidez,
                    "roi": result.roi,
                    "best_buy": result.buy,
                    "best_sell": result.sell,
                    "volumen_diario_real": result.volumen_diario_real,
                    "buy_order_count": buy_order_count,
                    "sell_order_count": sell_order_count,
                    "avg_daily_volume_7d": avg_daily_volume_7d,
                    "avg_daily_order_count_7d": avg_daily_order_count_7d,
                    "last_evaluated_at": now,
                })
                if status != previous_status:
                    insert_status_history(conn, row["type_id"], previous_status, status, now, reason)

                # El registro Excel/Sheets es un log de OPORTUNIDADES detectadas, no de todos
                # los ítems evaluados — solo se anota lo clasificado como POTENCIAL.
                if status == "POTENCIAL":
                    registro.append(
                        result.item, result.buy, result.sell,
                        result.volumen_deseado, result.volumen_diario_real,
                    )
                    append_opportunity_row([
                        result.item, result.buy, result.sell, result.volumen_deseado,
                        result.volumen_diario_real, result.beneficio, f"{result.spread_bruto:.2%}",
                        result.precio_min_venta, f"{result.roi:.2%}", result.evaluacion_spread,
                        f"{result.posicion_vs_volumen:.2%}", result.liquidez, result.recomendacion,
                    ])
                    if previous_status != "POTENCIAL":
                        events.append(NewOpportunity(result))

                if len(results) % 100 == 0:
                    conn.commit()  # visibilidad incremental para lectores (ej. la API) y checkpoint ante cortes

        conn.commit()
        dispatch(events)
        return pd.DataFrame([r.__dict__ for _, r in results])
    finally:
        conn.close()


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="Trae histórico completo (hasta 1 año)")
    parser.add_argument(
        "--volumen-deseado-fallback", type=float, default=None,
        help="Volumen fijo a usar SOLO si el wallet no está disponible (default: el parámetro "
             "'Volumen fijo si no hay wallet' en Ajustes)",
    )
    parser.add_argument(
        "--rescreen-only", action="store_true",
        help="Salta la ingesta ESI y recalcula el screening sobre los datos ya guardados en SQLite",
    )
    args = parser.parse_args()

    region_id = int(os.environ.get("ESI_REGION_ID", 10000002))
    base_url = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL)
    user_agent = os.environ.get("ESI_USER_AGENT", "eve-market-screener")
    db_path = os.environ.get("DB_PATH", "./storage/market.db")
    excel_path = os.environ.get("EXCEL_REGISTRO_PATH", "./reporting/eve-calculator-registro.xlsx")
    # Default pensado para una máquina de desarrollo con RAM de sobra. En hosts chicos
    # (ej. la VM Always Free de Oracle, 1GB RAM/2 vCPU) 20 threads concurrentes —cada
    # uno con su propia conexión HTTP y buffers— satura la RAM y termina en swap
    # thrashing (visto en vivo: la corrida se frenaba con swap casi lleno). Configurable
    # por env en vez de bajarlo para todos, así el dev local sigue con el valor rápido.
    max_workers = int(os.environ.get("MAX_INGEST_WORKERS", 20))

    init_db(db_path)

    start = time.time()
    with EsiClient(base_url=base_url, user_agent=user_agent) as client:
        if args.rescreen_only:
            conn = get_connection(db_path)
            try:
                type_ids = [r["type_id"] for r in conn.execute("SELECT type_id FROM item_type").fetchall()]
            finally:
                conn.close()
        else:
            type_ids = ingest(client, region_id, db_path, backfill=args.backfill, max_workers=max_workers)

        ingest_categories(client, db_path, type_ids, max_workers=max_workers)

    screen_opportunities(db_path, excel_path, args.volumen_deseado_fallback)

    logger.info("Pipeline completo en %.1fs", time.time() - start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
