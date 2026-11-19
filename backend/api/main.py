"""API REST de solo lectura sobre storage/market.db — rutas PÚBLICAS únicamente
(datos de mercado/Screener, sin nada personal). Las rutas privadas (wallet, órdenes
propias, ajustes, recomendación de sizing en vivo) viven en backend/api/private.py,
montadas bajo /api/private y protegidas por Cloudflare Access en el borde (T14).

Uso:
    uvicorn backend.api.main:app --reload --port 8001

Consumida por la PWA (frontend) y disponible para consultas ad-hoc. No dispara
ingesta ni screening: eso lo hacen los dos motores por separado (on-demand o
programados) — scheduler/run.py (mercado, cada 5 min) y scheduler/orders_run.py
(posiciones de tus órdenes, cada 5 min). Mayormente se lee lo que ya calcularon.
"""
import logging
import math
import os
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.analytics import private_router as analytics_private_router
from backend.api.analytics import router as analytics_router
from backend.api.deps import ITEM_JOIN, ITEM_SELECT_COLS, _db, resolve_market
from backend.api.indexnow import router as indexnow_router
from backend.api.market_pages import router as market_pages_router
from backend.api.pages import router as pages_router
from backend.api.private import router as private_router
from backend.api.ratelimit import install_rate_limit
from backend.api.seo import docs_kwargs, install_seo_middleware
from backend.api.schemas import (
    MarketOut,
    CategoryOut,
    HistoryPointOut,
    ItemDetailOut,
    ItemsPageOut,
    ItemStatusOut,
    OpportunityOut,
    UnitRecommendationOut,
    ScheduleOut,
    SnapshotOut,
    StatusChangeOut,
    SummaryOut,
)
from analytics.eve_calculator import (
    EveCalculatorConfig,
    beneficio_unitario,
    config_from_settings,
    evaluar_oportunidad,
    resolve_volumen_deseado,
)
from analytics.opportunity import evaluate_item, make_configs, parse_inputs_blob
from analytics.scoring import ScoreConfig, ScoreInputs, holding_days
from ingestion.schedule import get_next_run_times
from storage.db import DEFAULT_MARKET, get_app_settings_dict, init_db

load_dotenv()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Al arrancar, deja el esquema al día (migraciones aditivas e idempotentes de init_db). Tras un
    despliegue la API suele arrancar antes de que el motor corra init_db, y las consultas que usan columnas
    nuevas fallaban hasta el siguiente ciclo (2026-11-19: el detalle de un ítem dio 500 unos minutos)."""
    try:
        init_db(os.environ.get("DB_PATH", "./storage/market.db"))
    except Exception:  # la API debe arrancar aunque la base esté ocupada: el motor migrará en su ciclo
        logger.exception("No se pudo migrar el esquema al arrancar la API")
    yield


app = FastAPI(title="EveMarket Screener API", version="1.0.0", lifespan=lifespan, **docs_kwargs())
install_seo_middleware(app)
install_rate_limit(app)  # se registra después: corre antes que el resto y corta rápido

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

app.include_router(private_router)
app.include_router(analytics_private_router)
app.include_router(analytics_router)
app.include_router(pages_router)
app.include_router(market_pages_router)
app.include_router(indexnow_router)


TREND_LABELS = {"up", "down", "flat", "lowliq", "nodata"}
# Capital propio (ISK) con el que el visitante quiere ver el puntaje: recalcula solo lo que depende de él (liquidez,
# profundidad, eficiencia del capital, beneficio mínimo y rotación); margen y estabilidad no cambian.
CAPITAL_MIN, CAPITAL_MAX = 1_000_000.0, 1e13
ELIGIBILITIES = {"NO_ELIGIBLE", "ELIGIBLE", "RECOMMENDED"}
RECOMMENDATIONS = {"BUY_CANDIDATE", "WAIT", "REJECT"}
SCORE_CLASSES = {"EXCELLENT", "HIGH", "MODERATE", "LOW", "DISCARDED"}


def snap_capital(capital: float | None) -> float | None:
    """Redondea el capital pedido a 2 cifras significativas (123 M -> 120 M). El puntaje apenas cambia con un 5 %
    de diferencia, y así las peticiones comparten la caché en vez de recalcular todo el mercado por cada valor."""
    if capital is None:
        return None
    step = 10 ** (math.floor(math.log10(capital)) - 1)
    return float(round(capital / step) * step)


def settings_for_capital(conn, capital: float | None) -> dict:
    """Ajustes vigentes; con un capital propio, ese capital sustituye al de referencia del puntaje."""
    settings = get_app_settings_dict(conn)
    if capital is not None:
        settings = {**settings, "score_reference_capital": float(capital)}
    return settings


def _score_inputs(row) -> tuple[ScoreInputs, dict]:
    """Entradas del puntaje de una fila de item_status (más lo guardado en score_inputs)."""
    extras = parse_inputs_blob(row["score_inputs"])
    return ScoreInputs(
        roi=row["roi"], best_buy=row["best_buy"], volume_7d=row["avg_daily_volume_7d"],
        volume_30d=row["volumen_diario_real"], ops_7d=row["avg_daily_order_count_7d"],
        buy_orders=row["buy_order_count"], sell_orders=row["sell_order_count"], status=row["status"],
        price_cv=extras["cv"], buy_depth=extras["bd"], sell_depth=extras["sd"],
    ), extras


def build_assessment(row, conn, capital: float | None = None) -> dict | None:
    """Explicación completa del puntaje de un ítem, recalculada con el mismo código que el motor
    (analytics.opportunity.evaluate_item) a partir de la fila de item_status y de score_inputs. Si los
    ajustes cambiaron desde la última evaluación, `config_changed` lo dice (el número del listado es el
    guardado; el desglose usa la configuración actual). Con `capital`, se calcula para ese capital."""
    if "score_version" not in row.keys() or row["score_version"] is None:
        # Sin columna (la API arrancó antes que la migración) o ítem aún sin puntaje.
        return None
    inputs, extras = _score_inputs(row)
    score, assessment = evaluate_item(inputs, row["best_sell"], extras, settings_for_capital(conn, capital))
    return {
        "algorithm_version": score.version,
        "stored_version": row["score_version"],
        "config_changed": score.version != row["score_version"] and capital is None,
        "capital": capital,
        "evaluated_at": row["last_evaluated_at"],
        "data_age_min": extras["age"],
        "score": score.to_dict(),
        **assessment,
    }


# Recalcular el puntaje de un mercado entero (~17 mil ítems en Jita) cuesta ~1,4 s; los filtros y el orden por
# puntaje con un capital propio lo necesitan. Se guarda por (mercado, capital, ajustes, ciclo): el ciclo de precios
# (cada 5 min) cambia `last_evaluated_at` y con ello caduca la entrada, así que nunca se sirve un dato más viejo
# que el guardado en la base. Pocas entradas: cada una son unos 3 MB.
_RESCORE_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_RESCORE_LOCK = threading.Lock()
_RESCORE_COMPUTE = threading.Lock()  # un solo recálculo de mercado entero a la vez; los demás esperan y usan la caché
_RESCORE_CACHE_MAX = 6


def rescored_market(conn, market_id: str, capital: float, settings: dict, configs: tuple) -> dict:
    """{type_id: (score, score_class, eligibility, recommendation)} de todo el mercado para ese capital."""
    stamp = conn.execute("SELECT MAX(last_evaluated_at) FROM item_status WHERE market_id = ?", (market_id,)).fetchone()[0]
    key = (market_id, float(capital), stamp, hash(tuple(sorted(settings.items()))))
    def cached():
        with _RESCORE_LOCK:
            if key in _RESCORE_CACHE:
                _RESCORE_CACHE.move_to_end(key)
                return _RESCORE_CACHE[key]
        return None

    hit = cached()
    if hit is not None:
        return hit
    with _RESCORE_COMPUTE:
        hit = cached()  # otra petición pudo calcularlo mientras esperábamos
        if hit is not None:
            return hit
        result = {}
        for row in conn.execute(
                "SELECT * FROM item_status WHERE market_id = ? AND score_version IS NOT NULL", (market_id,)):
            updated = rescore_row(row, settings, configs)
            result[row["type_id"]] = (updated["score"], updated["score_class"], updated["eligibility"],
                                      updated["recommendation"])
        with _RESCORE_LOCK:
            _RESCORE_CACHE[key] = result
            while len(_RESCORE_CACHE) > _RESCORE_CACHE_MAX:
                _RESCORE_CACHE.popitem(last=False)
        return result


def build_unit_recommendation(status_row, snapshot_row, conn, capital: float | None,
                              assessment: dict | None) -> UnitRecommendationOut | None:
    """Unidades a comprar según el capital: la posición es capital x `position_size_pct_wallet` (10 %) y la cuenta es
    la misma del motor (evaluar_oportunidad, que ya recorta por liquidez). Sin capital elegido se usa el de
    referencia. Si la evaluación del motor es REJECT, las unidades sugeridas son 0 y `blocked_by` dice por qué."""
    settings = settings_for_capital(conn, capital)
    used_capital = float(settings["score_reference_capital"])
    buy = (snapshot_row["best_buy"] if snapshot_row is not None else None) or status_row["best_buy"]
    sell = (snapshot_row["best_sell"] if snapshot_row is not None else None) or status_row["best_sell"]
    if not buy or not sell or buy <= 0 or not status_row["volumen_diario_real"] or status_row["volumen_diario_real"] <= 0:
        return None  # sin precios o sin volumen no hay con qué calcular una posición (y evaluar_oportunidad divide por él)
    pct = float(settings["position_size_pct_wallet"])
    eve_config = config_from_settings(EveCalculatorConfig, settings)
    wanted = resolve_volumen_deseado(buy, used_capital, pct, settings["volumen_deseado_fallback"])
    result = evaluar_oportunidad(item=status_row["name"], buy=buy, sell=sell, volumen_deseado=wanted,
                                 volumen_diario_real=status_row["volumen_diario_real"], config=eve_config)
    action = assessment["recommendation"]["action"] if assessment else None
    blocked_by = list(assessment["eligibility"]["failed_filters"]) if assessment and action == "REJECT" else []
    unit_cost = buy * eve_config.buy_fee_factor
    # La cuenta del motor nunca baja de 1 unidad; si la posición no alcanza ni para una, no se recomienda comprar.
    max_units = int((used_capital * pct) // unit_cost)   # lo que cabe en la posición, comisión incluida
    affordable = max_units >= 1
    units = 0 if (action == "REJECT" or not affordable) else min(int(result.unidades_sugeridas or 0), max_units)
    if units == 0 and action == "BUY_CANDIDATE":
        # El motor de unidades dice "no ejecutar" (spread que no cubre costos) aunque la evaluación del puntaje
        # (con otros ajustes) lo daba por candidato: nunca se muestra "candidato a compra" con 0 unidades.
        action = "WAIT"
    days = holding_days(units, status_row["avg_daily_volume_7d"], config_from_settings(ScoreConfig, settings)) if units else None
    return UnitRecommendationOut(
        capital=used_capital, position_pct=pct, posicion_isk=round(used_capital * pct), volumen_deseado=round(wanted, 2),
        unidades_sugeridas=units, recomendacion=result.recomendacion, action=action, blocked_by=blocked_by,
        precio_unidad_isk=round(unit_cost), alcanza=affordable,
        inversion_isk=round(units * unit_cost), beneficio_neto_isk=round(units * beneficio_unitario(buy, sell, eve_config)),
        dias_rotacion=None if days is None else round(days, 2),
    )


def rescore_row(row, settings: dict, configs: tuple) -> dict:
    """La fila (como dict) con score / score_class / eligibility / recommendation recalculados con los ajustes
    dados (p. ej. con el capital del visitante). Las filas sin puntaje se devuelven igual."""
    out = dict(row)
    if "score_version" not in out or out["score_version"] is None:
        return out
    inputs, extras = _score_inputs(row)
    score, assessment = evaluate_item(inputs, row["best_sell"], extras, settings, configs)
    out.update(score=score.score, score_class=score.classification,
               eligibility=assessment["eligibility"]["status"], recommendation=assessment["recommendation"]["action"])
    return out


@app.get("/api/markets", response_model=list[MarketOut])
def list_markets_endpoint():
    """Mercados activos con sus conteos por estado y la última evaluación: alimenta el selector de
    mercado de la app y sirve para vigilar que cada mercado se actualice."""
    conn = _db()
    try:
        markets = conn.execute(
            "SELECT market_id, name, region_id FROM market WHERE enabled = 1 ORDER BY sort_order, market_id"
        ).fetchall()
        counts: dict[str, dict[str, int]] = {}
        for row in conn.execute("SELECT market_id, status, COUNT(*) AS n FROM item_status GROUP BY market_id, status"):
            counts.setdefault(row["market_id"], {})[row["status"]] = row["n"]
        last = {r["market_id"]: r["m"] for r in conn.execute(
            "SELECT market_id, MAX(last_evaluated_at) AS m FROM item_status GROUP BY market_id")}
        return [
            MarketOut(
                market_id=m["market_id"], name=m["name"], region_id=m["region_id"],
                counts=counts.get(m["market_id"], {}), total=sum(counts.get(m["market_id"], {}).values()),
                last_evaluated_at=last.get(m["market_id"]),
            )
            for m in markets
        ]
    finally:
        conn.close()


@app.get("/api/summary", response_model=SummaryOut)
def get_summary(market: str = DEFAULT_MARKET):
    conn = _db()
    try:
        market = resolve_market(conn, market)
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM item_status WHERE market_id = ? GROUP BY status", (market,),
        ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        last = conn.execute(
            "SELECT MAX(last_evaluated_at) as m FROM item_status WHERE market_id = ?", (market,),
        ).fetchone()
        return SummaryOut(
            counts=counts,
            total=sum(counts.values()),
            last_evaluated_at=last["m"],
        )
    finally:
        conn.close()


@app.get("/api/schedule", response_model=ScheduleOut)
def get_schedule():
    """Próximo disparo de cada tarea programada de Windows (ver ingestion/schedule.py).
    None para una tarea significa que todavía no está registrada — correr
    scripts/setup_task_scheduler.ps1."""
    return ScheduleOut(**get_next_run_times())


@app.get("/api/items", response_model=ItemsPageOut)
def list_items(
    market: str = DEFAULT_MARKET,
    status: str | None = None,
    category_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    min_roi: float | None = None,
    max_roi: float | None = None,
    min_spread: float | None = None,
    max_spread: float | None = None,
    min_buy: float | None = None,
    max_buy: float | None = None,
    min_sell: float | None = None,
    max_sell: float | None = None,
    min_volume: float | None = None,
    max_volume: float | None = None,
    trend: str | None = None,
    min_trend: float | None = None,
    max_trend: float | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    score_class: str | None = None,
    eligibility: str | None = None,
    recommendation: str | None = None,
    capital: float | None = Query(default=None, ge=CAPITAL_MIN, le=CAPITAL_MAX),
    sort: str = "volumen_diario_real",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    # Prioridad de descubrimiento: volumen diario real (rotación real) primero, ROI como
    # criterio secundario — se aplica siempre como desempate, sin importar el `sort` elegido.
    allowed_sort = {"spread_bruto", "roi", "last_evaluated_at", "name", "volumen_diario_real",
                     "best_buy", "best_sell", "avg_daily_order_count_7d", "price_trend", "score"}
    if sort not in allowed_sort:
        raise HTTPException(400, f"sort debe ser uno de {allowed_sort}")
    for name, value, allowed in (("score_class", score_class, SCORE_CLASSES), ("eligibility", eligibility, ELIGIBILITIES),
                                 ("recommendation", recommendation, RECOMMENDATIONS)):
        if value is not None and value not in allowed:
            raise HTTPException(400, f"{name} debe ser uno de {sorted(allowed)}")
    if order not in {"asc", "desc"}:
        raise HTTPException(400, "order debe ser 'asc' o 'desc'")
    if trend is not None and trend not in TREND_LABELS:
        raise HTTPException(400, f"trend debe ser uno de {sorted(TREND_LABELS)}")
    if offset < 0 or offset > 100_000:
        raise HTTPException(400, "offset debe estar entre 0 y 100000")
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit debe estar entre 1 y 500")

    capital = snap_capital(capital)
    # Con capital propio, los filtros y el orden por puntaje se aplican DESPUÉS de recalcularlo (el puntaje
    # guardado es el del capital de referencia y no coincidiría con lo que ve el visitante).
    recompute_all = capital is not None and (
        min_score is not None or score_class is not None or eligibility is not None
        or recommendation is not None or sort == "score")
    filters: list[str] = ["s.market_id = ?"]
    params: list = []
    if status:
        filters.append("s.status = ?")
        params.append(status)
    if category_id is not None:
        filters.append("c.category_id = ?")
        params.append(category_id)
    if trend:
        filters.append("s.price_trend_label = ?")
        params.append(trend)
    if not recompute_all:
        if min_score is not None:
            filters.append("s.score >= ?")
            params.append(min_score)
        for column, value in (("s.score_class", score_class), ("s.eligibility", eligibility),
                              ("s.recommendation", recommendation)):
            if value is not None:
                filters.append(f"{column} = ?")
                params.append(value)
    name_query = (q or "").strip()
    if name_query:
        # Búsqueda por nombre: contiene el texto, sin distinguir mayúsculas (LIKE de SQLite es
        # insensible a mayúsculas para ASCII). Se escapan % _ y \ para que valgan como texto.
        escaped = name_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append("i.name LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    for column, value in [
        ("s.roi", min_roi), ("s.spread_bruto", min_spread), ("s.best_buy", min_buy),
        ("s.best_sell", min_sell), ("s.volumen_diario_real", min_volume), ("s.price_trend", min_trend),
    ]:
        if value is not None:
            filters.append(f"{column} >= ?")
            params.append(value)
    for column, value in [
        ("s.roi", max_roi), ("s.spread_bruto", max_spread), ("s.best_buy", max_buy),
        ("s.best_sell", max_sell), ("s.volumen_diario_real", max_volume), ("s.price_trend", max_trend),
    ]:
        if value is not None:
            filters.append(f"{column} <= ?")
            params.append(value)

    where = f" WHERE {' AND '.join(filters)}" if filters else ""

    conn = _db()
    try:
        market_id = resolve_market(conn, market)
        params.insert(0, market_id)
        total = conn.execute(f"SELECT COUNT(*) as n {ITEM_JOIN}{where}", params).fetchone()["n"]

        sql_sort = "volumen_diario_real" if (recompute_all and sort == "score") else sort
        sort_col = "i.name" if sql_sort == "name" else f"s.{sql_sort}"
        tiebreaker = "" if sql_sort == "roi" else ", s.roi DESC"
        if sql_sort in ("price_trend", "score"):
            # Items without a reliable trend / without a score yet (NULL) always go last, whichever the direction.
            sort_col = f"(s.{sql_sort} IS NULL), {sort_col}"
        query = f"SELECT {ITEM_SELECT_COLS} {ITEM_JOIN}{where} ORDER BY {sort_col} {order.upper()}{tiebreaker}"

        if capital is None:
            rows = conn.execute(f"{query} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            return ItemsPageOut(items=[ItemStatusOut(**dict(r)) for r in rows], total=total, limit=limit, offset=offset)

        settings = settings_for_capital(conn, capital)
        configs = make_configs(settings)
        if not recompute_all:
            rows = conn.execute(f"{query} LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
            items = [rescore_row(r, settings, configs) for r in rows]
        else:
            # Solo se piden id y ROI de todas las filas (no las ~30 columnas de 17 mil): se filtra y ordena por el puntaje
            # recalculado y únicamente las filas de la página se leen completas. Antes cada petición construía 17 mil
            # diccionarios (~350 ms de CPU) y con varios clientes a la vez la mediana pasaba de 9 s.
            scores = rescored_market(conn, market_id, capital, settings, configs)
            ids_query = f"SELECT s.type_id, s.roi {ITEM_JOIN}{where} ORDER BY {sort_col} {order.upper()}{tiebreaker}"
            kept = []
            for type_id, roi in conn.execute(ids_query, params):
                hit = scores.get(type_id)
                if min_score is not None and (hit is None or hit[0] is None or hit[0] < min_score):
                    continue
                if score_class is not None and (hit is None or hit[1] != score_class):
                    continue
                if eligibility is not None and (hit is None or hit[2] != eligibility):
                    continue
                if recommendation is not None and (hit is None or hit[3] != recommendation):
                    continue
                kept.append((type_id, roi, hit))
            if sort == "score":
                # Sin puntaje siempre al final; el desempate es el ROI, como en el orden de SQL.
                kept.sort(key=lambda k: -k[1])
                sign = -1 if order == "desc" else 1
                kept.sort(key=lambda k: (k[2] is None or k[2][0] is None, sign * ((k[2][0] or 0) if k[2] else 0)))
            total = len(kept)
            page = kept[offset:offset + limit]
            by_id = {}
            if page:
                marks = ",".join("?" * len(page))
                for r in conn.execute(
                        f"SELECT {ITEM_SELECT_COLS} {ITEM_JOIN} WHERE s.market_id = ? AND s.type_id IN ({marks})",
                        [market_id, *[k[0] for k in page]]):
                    by_id[r["type_id"]] = dict(r)
            items = []
            for type_id, _roi, hit in page:
                row = by_id.get(type_id)
                if row is None:
                    continue
                if hit is not None:
                    row.update(score=hit[0], score_class=hit[1], eligibility=hit[2], recommendation=hit[3])
                items.append(row)
        return ItemsPageOut(items=[ItemStatusOut(**r) for r in items], total=total, limit=limit, offset=offset,
                            capital=capital)
    finally:
        conn.close()


@app.get("/api/categories", response_model=list[CategoryOut])
def list_categories(market: str = DEFAULT_MARKET):
    conn = _db()
    try:
        market = resolve_market(conn, market)
        rows = conn.execute(
            "SELECT DISTINCT c.category_id, c.category_name FROM item_category c "
            "JOIN item_status s ON s.type_id = c.type_id WHERE s.market_id = ? ORDER BY c.category_name",
            (market,),
        ).fetchall()
        return [CategoryOut(**dict(r)) for r in rows]
    finally:
        conn.close()


@app.get("/api/items/{type_id}", response_model=ItemDetailOut)
def get_item_detail(type_id: int, market: str = DEFAULT_MARKET,
                    capital: float | None = Query(default=None, ge=CAPITAL_MIN, le=CAPITAL_MAX)):
    conn = _db()
    try:
        market = resolve_market(conn, market)
        status_row = conn.execute(
            f"SELECT {ITEM_SELECT_COLS} {ITEM_JOIN} WHERE s.market_id = ? AND s.type_id = ?",
            (market, type_id),
        ).fetchone()
        if status_row is None:
            raise HTTPException(404, "Ítem no encontrado o sin clasificar todavía")

        history_rows = conn.execute(
            "SELECT date, avg_price, highest, lowest, volume, order_count "
            "FROM market_history WHERE market_id = ? AND type_id = ? ORDER BY date DESC LIMIT 90",
            (market, type_id),
        ).fetchall()

        snapshot_row = conn.execute(
            "SELECT captured_at, best_buy, best_sell, buy_volume, sell_volume, "
            "buy_order_count, sell_order_count, buy_depth_5pct, sell_depth_5pct, buy_gap_bp, sell_gap_bp, "
            "buy_top_permille, sell_top_permille "
            "FROM market_snapshot WHERE market_id = ? AND type_id = ? ORDER BY captured_at DESC LIMIT 1",
            (market, type_id),
        ).fetchone()

        opportunity_rows = conn.execute(
            "SELECT evaluated_at, buy, sell, volumen_deseado, volumen_diario_real, beneficio, "
            "spread_bruto, precio_min_venta, roi, evaluacion_spread, posicion_vs_volumen, "
            "liquidez, recomendacion FROM opportunity_log WHERE market_id = ? AND type_id = ? "
            "ORDER BY evaluated_at DESC LIMIT 20",
            (market, type_id),
        ).fetchall()

        capital = snap_capital(capital)
        status_dict = dict(status_row)
        if capital is not None:  # el número de la cabecera debe coincidir con el desglose del panel
            settings = settings_for_capital(conn, capital)
            status_dict = rescore_row(status_row, settings, make_configs(settings))
        assessment = build_assessment(status_row, conn, capital)
        return ItemDetailOut(
            status=ItemStatusOut(**status_dict),
            history=[HistoryPointOut(**dict(r)) for r in history_rows],
            latest_snapshot=SnapshotOut(**dict(snapshot_row)) if snapshot_row else None,
            latest_opportunities=[OpportunityOut(**dict(r)) for r in opportunity_rows],
            assessment=assessment,
            recommendation=build_unit_recommendation(status_row, snapshot_row, conn, capital, assessment),
        )
    finally:
        conn.close()


@app.get("/api/status-changes", response_model=list[StatusChangeOut])
def list_status_changes(limit: int = 50, market: str = DEFAULT_MARKET):
    if limit < 1 or limit > 200:
        raise HTTPException(400, "limit debe estar entre 1 y 200")
    conn = _db()
    try:
        market = resolve_market(conn, market)
        rows = conn.execute(
            "SELECT h.type_id, i.name, h.previous_status, h.new_status, h.changed_at, h.reason "
            "FROM item_status_history h JOIN item_type i ON i.type_id = h.type_id "
            "WHERE h.market_id = ? ORDER BY h.changed_at DESC LIMIT ?",
            (market, limit),
        ).fetchall()
        return [StatusChangeOut(**dict(r)) for r in rows]
    finally:
        conn.close()


# Build estático de la PWA (frontend/app/dist) — solo existe si se corrió `npm run
# build` (caso del Dockerfile de producción). En desarrollo local no está presente
# y la PWA se sirve aparte con `npm run dev` (Vite, puerto 5173) — por eso el mount
# es condicional, para no romper `uvicorn --reload` en dev. Va al final del archivo
# a propósito: un Mount en "/" es un catch-all, tiene que quedar después de todas las
# rutas /api/* para no taparlas.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "app" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
