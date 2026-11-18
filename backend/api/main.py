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
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.analytics import private_router as analytics_private_router
from backend.api.analytics import router as analytics_router
from backend.api.deps import ITEM_JOIN, ITEM_SELECT_COLS, _db, resolve_market
from backend.api.indexnow import router as indexnow_router
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
    ScheduleOut,
    SnapshotOut,
    StatusChangeOut,
    SummaryOut,
)
from ingestion.schedule import get_next_run_times
from storage.db import DEFAULT_MARKET

load_dotenv()

app = FastAPI(title="EveMarket Screener API", version="1.0.0", **docs_kwargs())
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
app.include_router(indexnow_router)


TREND_LABELS = {"up", "down", "flat", "lowliq", "nodata"}


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
    sort: str = "volumen_diario_real",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    # Prioridad de descubrimiento: volumen diario real (rotación real) primero, ROI como
    # criterio secundario — se aplica siempre como desempate, sin importar el `sort` elegido.
    allowed_sort = {"spread_bruto", "roi", "last_evaluated_at", "name", "volumen_diario_real",
                     "best_buy", "best_sell", "avg_daily_order_count_7d", "price_trend"}
    if sort not in allowed_sort:
        raise HTTPException(400, f"sort debe ser uno de {allowed_sort}")
    if order not in {"asc", "desc"}:
        raise HTTPException(400, "order debe ser 'asc' o 'desc'")
    if trend is not None and trend not in TREND_LABELS:
        raise HTTPException(400, f"trend debe ser uno de {sorted(TREND_LABELS)}")
    if offset < 0 or offset > 100_000:
        raise HTTPException(400, "offset debe estar entre 0 y 100000")
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit debe estar entre 1 y 500")

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
        params.insert(0, resolve_market(conn, market))
        total = conn.execute(f"SELECT COUNT(*) as n {ITEM_JOIN}{where}", params).fetchone()["n"]

        sort_col = "i.name" if sort == "name" else f"s.{sort}"
        tiebreaker = "" if sort == "roi" else ", s.roi DESC"
        if sort == "price_trend":
            # Items without a reliable trend (NULL) always go last, whichever the direction.
            sort_col = f"(s.price_trend IS NULL), {sort_col}"
        query = (
            f"SELECT {ITEM_SELECT_COLS} {ITEM_JOIN}{where} "
            f"ORDER BY {sort_col} {order.upper()}{tiebreaker} LIMIT ? OFFSET ?"
        )
        rows = conn.execute(query, [*params, limit, offset]).fetchall()
        return ItemsPageOut(
            items=[ItemStatusOut(**dict(r)) for r in rows],
            total=total, limit=limit, offset=offset,
        )
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
def get_item_detail(type_id: int, market: str = DEFAULT_MARKET):
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
            "buy_order_count, sell_order_count "
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

        return ItemDetailOut(
            status=ItemStatusOut(**dict(status_row)),
            history=[HistoryPointOut(**dict(r)) for r in history_rows],
            latest_snapshot=SnapshotOut(**dict(snapshot_row)) if snapshot_row else None,
            latest_opportunities=[OpportunityOut(**dict(r)) for r in opportunity_rows],
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
