"""Motor Analizador de Mercado: ingesta ESI -> SQLite -> analítica -> screening
EveCalculator -> reporting. Sin flags corre el pipeline completo (modo local/Windows, ver
scripts/setup_task_scheduler.ps1). En producción se parte en dos procesos independientes:
`--prices-only` (órdenes -> snapshots -> screening, cada pocos minutos) y `--history-only`
(histórico diario de ESI, una vez al día). Procesa los mercados activos de la tabla `market`
(o los de `--markets`), uno tras otro y aislados: si uno falla, los demás siguen.

No toca tus órdenes de personaje — eso lo hace el motor de posiciones
(scheduler/orders_run.py), separado y con una cadencia mucho más ágil (cada 5 min).
Ambos motores comparten el mismo componente de notificación (notifications/telegram_bot.py).

Uso:
    python -m scheduler.run --backfill      # primera ejecución: histórico completo
    python -m scheduler.run                 # pipeline completo (snapshot + history del día + screening)
    python -m scheduler.run --prices-only   # ciclo rápido: órdenes y cálculos con el histórico ya guardado
    python -m scheduler.run --history-only  # proceso diario: solo el histórico de mercado de ESI
"""
import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from statistics import median

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
from analytics.opportunity import evaluate_item, inputs_blob
from analytics.sanity import SanityConfig, is_price_sane
from analytics.scoring import ScoreInputs
from analytics.trend import TrendConfig, compute_price_trends
from analytics.trend_alerts import TrendAlertState, advance
from ingestion.esi_client import DEFAULT_BASE_URL, EsiClient
from ingestion.markets import Market, UnknownMarketError, list_markets
from ingestion.wallet import get_current_wallet_balance
from reporting.excel_writer import EveCalculatorRegistro
from notifications.events import NewOpportunity, TrendChanged, dispatch, flush_notifications
from storage.db import (
    DEFAULT_MARKET,
    active_order_sides,
    get_app_settings_dict,
    get_cached_category_type_ids,
    get_cached_group,
    get_connection,
    get_item_status,
    get_trend_alert_state,
    init_db,
    insert_opportunity,
    insert_status_history,
    prune_old_snapshots,
    purge_opportunity_log,
    recent_opportunity_times,
    save_trend_alert_state,
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

HISTORY_WINDOW = 30  # filas de histórico por ítem que usa el screening (ventana de 30 días)

# opportunity_log: un ítem se registra como mucho una vez por intervalo (y siempre que cambie de
# estado). Antes se insertaba una fila por ítem y por ciclo: con ciclos de 5 min eran ~4,7 millones
# de filas al día. La app solo muestra la última recomendación del ítem.
DEFAULT_LOG_INTERVAL_MINUTES = 60            # ítems en estados útiles
DEFAULT_LOG_DISCARDED_INTERVAL_MINUTES = 720  # ítems DESCARTADO
DEFAULT_LOG_RETENTION_DAYS = 3


def _log_settings() -> tuple[float, float, float]:
    return (
        float(os.environ.get("OPPORTUNITY_LOG_INTERVAL_MIN", DEFAULT_LOG_INTERVAL_MINUTES)),
        float(os.environ.get("OPPORTUNITY_LOG_DISCARDED_INTERVAL_MIN", DEFAULT_LOG_DISCARDED_INTERVAL_MINUTES)),
        float(os.environ.get("OPPORTUNITY_LOG_RETENTION_DAYS", DEFAULT_LOG_RETENTION_DAYS)),
    )


def opportunity_log_due(status: str, previous_status: str | None, last_logged: str | None,
                        now: datetime, interval_min: float, discarded_interval_min: float) -> bool:
    """True si hay que registrar este ítem ahora: cambió de estado, nunca se registró o ya pasó
    el intervalo que le toca a su estado."""
    if previous_status is None or status != previous_status or last_logged is None:
        return True
    minutes = discarded_interval_min if status == "DESCARTADO" else interval_min
    return last_logged < (now - timedelta(minutes=minutes)).isoformat()
DEFAULT_SNAPSHOT_RETENTION_HOURS = 6


def snapshot_retention_hours() -> float:
    """Horas de snapshots de órdenes que se conservan. SNAPSHOT_RETENTION_HOURS manda; si solo
    está el SNAPSHOT_RETENTION_DAYS de versiones anteriores, se respeta (días * 24)."""
    hours = os.environ.get("SNAPSHOT_RETENTION_HOURS")
    if hours:
        return float(hours)
    days = os.environ.get("SNAPSHOT_RETENTION_DAYS")
    if days:
        return float(days) * 24
    return DEFAULT_SNAPSHOT_RETENTION_HOURS


def ingest_orders(client: EsiClient, region_id: int, db_path: str, market_id: str = DEFAULT_MARKET) -> list[int]:
    """Parte rápida de la ingesta: tipos activos, libro de órdenes de la región y snapshots.
    Los nombres solo se piden para los tipos que todavía no están en `item_type` (o quedaron con
    el nombre provisional `type_N`): ya no se resuelven los ~19.500 en cada ciclo."""
    conn = get_connection(db_path)
    captured_at = datetime.now(timezone.utc).isoformat()

    try:
        type_ids = client.get_active_type_ids(region_id)
        logger.info("Tipos activos en la región %s: %d", region_id, len(type_ids))

        orders = client.get_orders(region_id)
        orders_by_type = build_orders_by_type(orders)

        known_names = {
            row["type_id"]: row["name"]
            for row in conn.execute("SELECT type_id, name FROM item_type")
            if not str(row["name"]).startswith("type_")
        }
        missing = [t for t in type_ids if t not in known_names]
        new_names = client.get_type_names_bulk(missing) if missing else {}
        for type_id in type_ids:
            name = known_names.get(type_id) or new_names.get(type_id, f"type_{type_id}")
            upsert_item_type(conn, type_id, name)
            snapshot = orders_by_type.get(type_id, {})
            upsert_market_snapshot(conn, type_id, captured_at, snapshot, market_id=market_id)
        conn.commit()
        logger.info("Snapshot de órdenes cargado para %d tipos (%d nombres nuevos)", len(type_ids), len(missing))

        keep_hours = snapshot_retention_hours()
        deleted = prune_old_snapshots(conn, keep_hours=keep_hours, market_id=market_id)
        if deleted:
            logger.info("Snapshots de más de %g h borrados: %d filas", keep_hours, deleted)
        return type_ids
    finally:
        conn.close()


HISTORY_MAX_FAILURE_RATE = 0.02  # fracción de tipos con error que hace fallar la corrida de histórico
HISTORY_CURRENT_COVERAGE = 0.9   # el día de ayer cuenta como completo con el 90 % de los tipos del día anterior


HISTORY_PUBLISH_UTC = (11, 15)   # la ESI publica el día D-1 a las 11:05 UTC; margen de 10 min
HISTORY_AUDIT_DAYS = 30          # ventana que revisa la auditoría de huecos
HISTORY_GAP_COVERAGE = 0.5       # un día con menos de la mitad de los tipos habituales cuenta como hueco


def history_expected_date(now: datetime | None = None) -> date:
    """Último día de histórico que la ESI ya debe tener publicado: ayer (UTC) desde las 11:15, y
    anteayer antes de esa hora (así las corridas nocturnas del cron no repiten trabajo inútil)."""
    now = now or datetime.now(timezone.utc)
    published = (now.hour, now.minute) >= HISTORY_PUBLISH_UTC
    return now.date() - timedelta(days=1 if published else 2)


def _history_counts(db_path: str, market_id: str, since: str) -> dict[str, int]:
    conn = get_connection(db_path)
    try:
        return {
            r["date"]: r["n"]
            for r in conn.execute(
                "SELECT date, COUNT(*) AS n FROM market_history WHERE market_id = ? AND date >= ? GROUP BY date",
                (market_id, since),
            )
        }
    finally:
        conn.close()


def history_is_current(db_path: str, market_id: str, now: datetime | None = None) -> bool:
    """¿Ya está guardado el último día publicado de este mercado? El cron del histórico reintenta cada
    hora y esta comprobación hace que las corridas posteriores a una exitosa no hagan nada. Se compara
    la cobertura (tipos con fila ese día frente a los del día anterior) para que una corrida cortada a
    medias se reintente."""
    target = history_expected_date(now)
    counts = _history_counts(db_path, market_id, (target - timedelta(days=1)).isoformat())
    have, previous = counts.get(target.isoformat(), 0), counts.get((target - timedelta(days=1)).isoformat(), 0)
    if previous == 0:
        return have > 0
    return have >= previous * HISTORY_CURRENT_COVERAGE


def history_gaps(db_path: str, market_id: str, now: datetime | None = None,
                 days: int = HISTORY_AUDIT_DAYS) -> list[str]:
    """Fechas (ascendentes) de la ventana de auditoría sin histórico o con menos de la mitad de la
    cobertura mediana de ese mercado. Solo se miran los días desde el primero que tiene datos (un
    mercado nuevo no tiene "huecos" antes de existir)."""
    end = history_expected_date(now)
    counts = _history_counts(db_path, market_id, (end - timedelta(days=days - 1)).isoformat())
    counts = {d: n for d, n in counts.items() if d <= end.isoformat()}
    if not counts:
        return []
    typical = median(counts.values())
    day = date.fromisoformat(min(counts))
    gaps = []
    while day <= end:
        if counts.get(day.isoformat(), 0) < typical * HISTORY_GAP_COVERAGE:
            gaps.append(day.isoformat())
        day += timedelta(days=1)
    return gaps


def audit_history(db_path: str, markets: list[str], now: datetime | None = None) -> dict[str, list[str]]:
    """Huecos de histórico por mercado (solo lectura; no llama a la ESI)."""
    return {m: history_gaps(db_path, m, now) for m in markets}


def ingest_history(client: EsiClient, region_id: int, db_path: str, type_ids: list[int],
                   backfill: bool = False, max_workers: int = 20, market_id: str = DEFAULT_MARKET,
                   history_days: int | None = None) -> None:
    """Parte lenta de la ingesta: el histórico diario de mercado de cada tipo (una petición por
    tipo). Solo cambia una vez al día, así que en producción corre en su propio proceso.

    Las filas se acumulan en memoria y se escriben en ráfagas cortas cada 100 tipos. Abrir la
    transacción al llegar la primera respuesta y cerrarla 100 tipos después la dejaba abierta
    casi todo el tiempo (la mayor parte se va esperando a ESI): como SQLite solo admite un
    escritor, el ciclo de precios que corre al mismo tiempo no conseguía escribir y fallaba con
    "database is locked" aun con el busy_timeout de 30 s."""
    conn = get_connection(db_path)
    pending: list[tuple[int, dict]] = []
    # Última fecha guardada por tipo: la ESI devuelve el año completo en cada petición, así que
    # el modo diario guarda TODO lo posterior a esa fecha. Si una corrida falla (ESI caída), la
    # siguiente rellena el hueco en vez de dejarlo para siempre (antes solo se guardaba la última
    # fila y un día perdido no se recuperaba).
    latest_date: dict[int, str] = {}
    if not backfill:
        latest_date = {
            r["type_id"]: r["last_date"]
            for r in conn.execute(
                "SELECT type_id, MAX(date) AS last_date FROM market_history WHERE market_id = ? GROUP BY type_id",
                (market_id,),
            )
        }
    failures = 0

    def flush() -> None:
        for pending_type_id, pending_row in pending:
            upsert_market_history(conn, pending_type_id, pending_row, market_id=market_id)
        conn.commit()
        pending.clear()

    try:
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
                        failures += 1
                    history = []
                except Exception:
                    logger.exception("Fallo al traer histórico de type_id=%s", type_id)
                    failures += 1
                    history = []

                if backfill:
                    if history_days is not None:
                        oldest = (datetime.now(timezone.utc) - timedelta(days=history_days)).date().isoformat()
                        history = [row for row in history if row["date"] >= oldest]
                    pending.extend((type_id, row) for row in history)
                elif history:
                    known = latest_date.get(type_id)
                    if known is None:
                        pending.append((type_id, history[-1]))
                    else:
                        pending.extend((type_id, row) for row in history if row["date"] > known)

                done += 1
                if done % 100 == 0:
                    flush()
                    logger.info("Histórico procesado: %d/%d", done, len(type_ids))

        flush()
        logger.info("Histórico completado para %d tipos", len(type_ids))
        if failures > max(10, len(type_ids) * HISTORY_MAX_FAILURE_RATE):
            # Lo traído ya quedó guardado; fallar hace que el mercado figure como fallido y que el
            # cron reintente (history_is_current sigue diciendo "no al día" hasta cubrir el día).
            raise RuntimeError(f"Histórico de {market_id}: fallaron {failures} de {len(type_ids)} tipos")
    finally:
        conn.close()


def ingest(client: EsiClient, region_id: int, db_path: str, backfill: bool, max_workers: int = 20,
           market_id: str = DEFAULT_MARKET, history_days: int | None = None) -> list[int]:
    """Ingesta completa (órdenes + histórico): lo que corre sin flags."""
    type_ids = ingest_orders(client, region_id, db_path, market_id=market_id)
    ingest_history(client, region_id, db_path, type_ids, backfill=backfill, max_workers=max_workers,
                   market_id=market_id, history_days=history_days)
    logger.info("Ingesta completada para %d tipos", len(type_ids))
    return type_ids


def ingest_categories(client: EsiClient, db_path: str, type_ids: list[int], max_workers: int = 20) -> None:
    """Cachea categoría/grupo por ítem (filtro por categoría).

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


def _int_or_none(value) -> int | None:
    """Entero de una celda de pandas (NaN / None -> None)."""
    return None if value is None or pd.isna(value) else int(value)


def _age_minutes(captured_at, now: datetime) -> float | None:
    """Antigüedad en minutos del snapshot de órdenes (None si la fecha falta o no se entiende)."""
    if not captured_at:
        return None
    try:
        moment = datetime.fromisoformat(str(captured_at))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max((now - moment).total_seconds() / 60, 0.0)


def screen_opportunities(db_path: str, excel_path: str,
                          fallback_volumen_deseado: float | None = None,
                          market_id: str = DEFAULT_MARKET) -> pd.DataFrame:
    conn = get_connection(db_path)
    try:
        settings = get_app_settings_dict(conn)
        eve_config = config_from_settings(EveCalculatorConfig, settings)
        sanity_config = config_from_settings(SanityConfig, settings)
        trend_config = config_from_settings(TrendConfig, settings)
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

        # Solo lo que el screening realmente usa: el ÚLTIMO snapshot de cada ítem y sus
        # últimas HISTORY_WINDOW filas de histórico (más abajo se hace tail(30)/tail(7)
        # por ítem). Cargar las tablas completas (1,3 GB en la VM de 1 GB de RAM) llevaba
        # al swap thrashing y la corrida nunca terminaba.
        snapshot = pd.read_sql_query(
            "SELECT s.*, i.name FROM market_snapshot s JOIN item_type i ON i.type_id = s.type_id "
            "WHERE s.market_id = ? AND s.captured_at = (SELECT MAX(s2.captured_at) FROM market_snapshot s2 "
            "WHERE s2.market_id = s.market_id AND s2.type_id = s.type_id)",
            conn, params=(market_id,),
        )
        history = pd.read_sql_query(
            "SELECT type_id, date, avg_price, volume, order_count FROM ("
            "SELECT type_id, date, avg_price, volume, order_count, "
            "ROW_NUMBER() OVER (PARTITION BY type_id ORDER BY date DESC) AS rn "
            "FROM market_history WHERE market_id = ?) WHERE rn <= ?",
            conn, params=(market_id, HISTORY_WINDOW),
        )

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

        trends = compute_price_trends(history, trend_config)
        # Volatilidad: coeficiente de variación del precio medio diario (30 d); sin 5 observaciones no se calcula.
        price_stats = recent_history.groupby("type_id")["avg_price"].agg(["mean", "std", "count"])
        price_cv = (price_stats["std"] / price_stats["mean"]).where(price_stats["count"] >= 5)
        reading_date = str(history["date"].max()) if not history.empty else None
        market_row = conn.execute("SELECT name, region_id FROM market WHERE market_id = ?", (market_id,)).fetchone()
        market_name = market_row["name"] if market_row else market_id
        my_orders = active_order_sides(conn, market_row["region_id"]) if market_row else {}
        trend_alert_min_ops = settings["trend_alert_min_ops_per_day"]

        merged = latest_snapshot.merge(recent_volume, on="type_id", how="inner")
        merged = merged.merge(reference_price, on="type_id", how="inner")
        merged = merged.merge(avg_daily_volume_7d, on="type_id", how="inner")
        merged = merged.merge(avg_daily_order_count_7d, on="type_id", how="inner")
        merged = merged.dropna(subset=["best_buy", "best_sell"])
        merged = merged[(merged["best_buy"] > 0) & (merged["volumen_diario_real"] > 0)]

        results = []
        events: list = []
        log_interval, log_discarded_interval, log_retention_days = _log_settings()
        run_start = datetime.now(timezone.utc)
        last_logged = recent_opportunity_times(
            conn, (run_start - timedelta(minutes=max(log_interval, log_discarded_interval))).isoformat(),
            market_id=market_id,
        )
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
                now_dt = datetime.now(timezone.utc)
                now = now_dt.isoformat()

                # Recategorización: todo ítem queda clasificado, sin importar si termina
                # registrado como oportunidad en Excel/Sheets o no.
                buy_order_count = int(row.get("buy_order_count", 0) or 0)
                sell_order_count = int(row.get("sell_order_count", 0) or 0)
                avg_daily_volume_7d = float(row["avg_daily_volume_7d"])
                avg_daily_order_count_7d = float(row["avg_daily_order_count_7d"])

                price_sane = is_price_sane(row["best_buy"], row["best_sell"], row["reference_price"], sanity_config)
                if price_sane:
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
                trend = trends.loc[row["type_id"]] if row["type_id"] in trends.index else None
                previous = get_item_status(conn, row["type_id"], market_id=market_id)
                previous_status = previous["status"] if previous else None

                # Puntaje 0-100 y evaluación determinista (complementan al estado; no lo cambian).
                cv = price_cv.get(row["type_id"])
                price_cv_value = None if cv is None or pd.isna(cv) else float(cv)
                data_age_min = _age_minutes(row.get("captured_at"), now_dt)
                buy_depth, sell_depth = _int_or_none(row.get("buy_depth_5pct")), _int_or_none(row.get("sell_depth_5pct"))
                score_result, assessment = evaluate_item(
                    ScoreInputs(
                        roi=result.roi, best_buy=result.buy, volume_7d=avg_daily_volume_7d,
                        volume_30d=result.volumen_diario_real, ops_7d=avg_daily_order_count_7d,
                        buy_orders=buy_order_count, sell_orders=sell_order_count, status=status,
                        price_cv=price_cv_value, buy_depth=buy_depth, sell_depth=sell_depth,
                    ),
                    result.sell, {"age": data_age_min, "sane": price_sane}, settings,
                )

                upsert_item_status(conn, {
                    "score": score_result.score,
                    "score_class": score_result.classification,
                    "eligibility": assessment["eligibility"]["status"],
                    "recommendation": assessment["recommendation"]["action"],
                    "score_version": score_result.version,
                    "score_inputs": inputs_blob(price_cv_value, data_age_min, price_sane, buy_depth, sell_depth),
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
                    "price_trend": None if trend is None or pd.isna(trend["price_trend"]) else float(trend["price_trend"]),
                    "price_trend_label": "nodata" if trend is None else trend["price_trend_label"],
                    "price_trend_threshold": (
                        None if trend is None or pd.isna(trend["price_trend_threshold"])
                        else float(trend["price_trend_threshold"])
                    ),
                }, market_id=market_id)
                if (trend is not None and reading_date and int(row["type_id"]) in my_orders
                        and avg_daily_order_count_7d >= trend_alert_min_ops):
                    prev_state = get_trend_alert_state(conn, market_id, int(row["type_id"]))
                    state, alert = advance(
                        TrendAlertState(**prev_state) if prev_state else None,
                        str(trend["price_trend_label"]), reading_date,
                    )
                    save_trend_alert_state(conn, market_id, int(row["type_id"]), state.__dict__)
                    if alert and not pd.isna(trend["price_trend"]):
                        events.append(TrendChanged(
                            item_name=row["name"], market_name=market_name,
                            label=str(trend["price_trend_label"]), change=float(trend["price_trend"]),
                            threshold=float(trend["price_trend_threshold"]),
                            ops_per_day=avg_daily_order_count_7d,
                            sides=tuple(sorted(my_orders[int(row["type_id"])])),
                        ))
                if status != previous_status:
                    insert_status_history(conn, row["type_id"], previous_status, status, now, reason,
                                          market_id=market_id)

                if opportunity_log_due(status, previous_status, last_logged.get(row["type_id"]), now_dt,
                                       log_interval, log_discarded_interval):
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
                    }, market_id=market_id)

                # El registro Excel es un log de OPORTUNIDADES detectadas, no de todos
                # los ítems evaluados — solo se anota lo clasificado como POTENCIAL.
                if status == "POTENCIAL":
                    registro.append(
                        result.item, result.buy, result.sell,
                        result.volumen_deseado, result.volumen_diario_real,
                    )
                    if previous_status != "POTENCIAL":
                        events.append(NewOpportunity(result))

                if len(results) % 100 == 0:
                    conn.commit()  # visibilidad incremental para lectores (ej. la API) y checkpoint ante cortes

        conn.commit()
        purged = purge_opportunity_log(conn, log_retention_days)
        if purged:
            logger.info("opportunity_log: %d filas de más de %g días borradas", purged, log_retention_days)
        dispatch(events)
        return pd.DataFrame([r.__dict__ for _, r in results])
    finally:
        conn.close()


def _run_market(client: EsiClient, market: Market, db_path: str, excel_path: str, args, max_workers: int) -> None:
    """Un mercado completo según el modo pedido (ver main)."""
    market_id, region_id = market.market_id, market.region_id
    if args.history_only:
        backfill, history_days = args.backfill, args.history_days
        if not backfill:
            gaps = history_gaps(db_path, market_id)
            if gaps:
                # Días sin datos (caída larga de la ESI): se rellenan desde el primer hueco, sin esperar
                # a que alguien lo haga a mano.
                backfill = True
                history_days = (datetime.now(timezone.utc).date() - date.fromisoformat(gaps[0])).days + 1
                logger.warning("Huecos de histórico en %s: %s; se rellenan los últimos %d días",
                               market_id, ", ".join(gaps), history_days)
            elif history_is_current(db_path, market_id):
                logger.info("Histórico de %s ya al día; nada que hacer", market_id)
                return
        type_ids = client.get_active_type_ids(region_id)
        ingest_history(client, region_id, db_path, type_ids, backfill=backfill, max_workers=max_workers,
                       market_id=market_id, history_days=history_days)
        return

    if args.rescreen_only:
        conn = get_connection(db_path)
        try:
            type_ids = [r["type_id"] for r in conn.execute("SELECT type_id FROM item_type").fetchall()]
        finally:
            conn.close()
    elif args.prices_only:
        type_ids = ingest_orders(client, region_id, db_path, market_id=market_id)
    else:
        type_ids = ingest(client, region_id, db_path, backfill=args.backfill, max_workers=max_workers,
                          market_id=market_id, history_days=args.history_days)

    ingest_categories(client, db_path, type_ids, max_workers=max_workers)
    screen_opportunities(db_path, excel_path, args.volumen_deseado_fallback, market_id=market_id)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="Trae histórico completo (hasta 1 año)")
    parser.add_argument(
        "--history-days", type=int, default=None,
        help="Con --backfill, guarda solo los últimos N días del histórico (el screening usa 30); útil para "
             "rellenar un mercado nuevo sin guardar un año entero",
    )
    parser.add_argument(
        "--markets", default=None,
        help="Mercados a procesar, separados por coma (p. ej. jita,amarr). Por defecto los activos en la tabla "
             "market; con esta opción se puede procesar uno todavía desactivado (rellenar su histórico)",
    )
    parser.add_argument(
        "--volumen-deseado-fallback", type=float, default=None,
        help="Volumen fijo a usar SOLO si el wallet no está disponible (default: el parámetro "
             "'Volumen fijo si no hay wallet' en Ajustes)",
    )
    parser.add_argument(
        "--rescreen-only", action="store_true",
        help="Salta la ingesta ESI y recalcula el screening sobre los datos ya guardados en SQLite",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--prices-only", action="store_true",
        help="Ciclo rápido: órdenes -> snapshots -> screening con el histórico ya guardado (sin bajar histórico)",
    )
    mode.add_argument(
        "--history-only", action="store_true",
        help="Solo baja el histórico de mercado de ESI (proceso diario); no recalcula el screening",
    )
    mode.add_argument(
        "--audit-history", action="store_true",
        help="Solo lectura: lista los días sin histórico (o con cobertura baja) de los últimos 30 días por "
             "mercado; sale con código 1 si hay huecos. No llama a la ESI",
    )
    args = parser.parse_args()
    if args.backfill and args.prices_only:
        parser.error("--backfill descarga histórico: no se combina con --prices-only")
    if args.rescreen_only and args.history_only:
        parser.error("--rescreen-only no se combina con --history-only")
    if args.history_days is not None and not args.backfill:
        parser.error("--history-days solo tiene sentido con --backfill")
    if args.history_days is not None and args.history_days < 1:
        parser.error("--history-days debe ser al menos 1")

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
    requested = [m.strip() for m in args.markets.split(",") if m.strip()] if args.markets else None
    try:
        markets = list_markets(db_path, requested)
    except UnknownMarketError as exc:
        parser.error(str(exc))
    if not markets:
        logger.warning("No hay mercados activos en la tabla market: no hay nada que procesar")
        return 0

    if args.audit_history:
        found = {m: g for m, g in audit_history(db_path, [m.market_id for m in markets]).items() if g}
        for market_id, gaps in found.items():
            logger.warning("Histórico de %s con huecos: %s", market_id, ", ".join(gaps))
        if not found:
            logger.info("Histórico sin huecos en los últimos %d días: %s", HISTORY_AUDIT_DAYS,
                        ", ".join(m.market_id for m in markets))
        return 1 if found else 0

    start = time.time()
    failed: list[str] = []
    with EsiClient(base_url=base_url, user_agent=user_agent) as client:
        for market in markets:
            market_start = time.time()
            try:
                _run_market(client, market, db_path, excel_path, args, max_workers)
                logger.info("Mercado %s completo en %.1fs", market.market_id, time.time() - market_start)
            except Exception:
                # Un mercado que falla (ESI, datos) no debe dejar sin actualizar a los demás.
                logger.exception("Fallo en el mercado %s; se sigue con los demás", market.market_id)
                failed.append(market.market_id)

    if args.history_only:
        logger.info("Histórico completo en %.1fs", time.time() - start)
    else:
        logger.info("Pipeline completo en %.1fs", time.time() - start)
    if failed:
        logger.error("Mercados con fallo: %s", ", ".join(failed))
    # Después del log: la duración del ciclo no incluye la espera a Telegram.
    flush_notifications()
    return 1 if failed and len(failed) == len(markets) else 0


if __name__ == "__main__":
    raise SystemExit(main())
