"""Métricas de uso con consentimiento: visitas, tiempo activo y retención.

Solo recibe datos de quien aceptó el aviso (frontend/app/public/analytics.js): un ID aleatorio
guardado en el navegador, un ID de visita y los segundos con la página visible. No se guarda la IP
ni el user agent. Quien retira el consentimiento pide borrar sus filas (POST /api/analytics/forget).
Los datos se conservan 395 días (13 meses) y después se borran solos.

El informe vive bajo /api/private (Cloudflare Access): GET /api/private/analytics/summary.
"""
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.api.deps import _db, require_cf_access_header
from backend.api.security import CANONICAL_HOST, check_same_origin
from storage.db import ANALYTICS_SCHEMA

RETENTION_DAYS = 395
MAX_ACTIVE_SECONDS = 4 * 3600
MAX_PAGEVIEWS_PER_VISIT = 500
_ID_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")
_HOST_RE = re.compile(r"^[a-z0-9.-]{1,100}$")

router = APIRouter(prefix="/api/analytics", tags=["analytics"], include_in_schema=False)
private_router = APIRouter(
    prefix="/api/private/analytics", dependencies=[Depends(require_cf_access_header)],
)

_purge_lock = threading.Lock()
_last_purge = 0.0
_schema_ready: set[str] = set()


def _ensure_schema(conn) -> None:
    """La API puede arrancar antes de que un motor corra init_db (p. ej. tras un despliegue):
    las tablas de analíticas se crean aquí la primera vez que se usan (CREATE IF NOT EXISTS)."""
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    if path in _schema_ready:
        return
    conn.executescript(ANALYTICS_SCHEMA)
    _schema_ready.add(path)


class PingIn(BaseModel):
    v: str  # ID del visitante (aleatorio, guardado en el navegador)
    s: str  # ID de la visita (una pestaña, hasta 30 min sin actividad)
    p: str = Field(max_length=200)  # ruta de la página
    a: int = Field(ge=0, le=MAX_ACTIVE_SECONDS)  # segundos activos acumulados en esta visita
    e: Literal["view", "ping"] = "ping"
    r: str = Field(default="", max_length=100)  # host del referente, si lo hay
    l: str = Field(default="", max_length=5)  # idioma  # noqa: E741


class ForgetIn(BaseModel):
    v: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _clean_path(path: str) -> str:
    path = path.split("?")[0].split("#")[0]
    return path if path.startswith("/") else "/"


def _check_ids(*ids: str) -> None:
    if not all(_ID_RE.match(i) for i in ids):
        raise HTTPException(400, "Identificador inválido.")


def purge_old(conn, now: datetime | None = None) -> None:
    cutoff = _iso((now or _now()) - timedelta(days=RETENTION_DAYS))
    conn.execute("DELETE FROM analytics_visit WHERE started_at < ?", (cutoff,))
    conn.execute("DELETE FROM analytics_visitor WHERE last_seen < ?", (cutoff,))


def _maybe_purge(conn) -> None:
    global _last_purge
    with _purge_lock:
        if time.monotonic() - _last_purge < 86400 and _last_purge:
            return
        _last_purge = time.monotonic()
    purge_old(conn)


@router.post("/ping", status_code=204)
def ping(body: PingIn, request: Request) -> Response:
    check_same_origin(request)
    _check_ids(body.v, body.s)
    now = _now()
    stamp = _iso(now)
    conn = _db()
    try:
        _ensure_schema(conn)
        visit = conn.execute(
            "SELECT visitor_id, started_at, active_seconds, pageviews FROM analytics_visit "
            "WHERE visit_id = ?", (body.s,),
        ).fetchone()
        if visit is None:
            ref = body.r.lower()
            ref = ref if _HOST_RE.match(ref) and not ref.endswith(CANONICAL_HOST) else ""
            lang = body.l.lower() if body.l.isalpha() else ""
            conn.execute(
                "INSERT INTO analytics_visitor (visitor_id, first_seen, last_seen, visit_count, lang) "
                "VALUES (?, ?, ?, 1, ?) ON CONFLICT(visitor_id) DO UPDATE SET "
                "last_seen = excluded.last_seen, visit_count = visit_count + 1, "
                "lang = COALESCE(NULLIF(excluded.lang, ''), lang)",
                (body.v, stamp, stamp, lang),
            )
            conn.execute(
                "INSERT INTO analytics_visit (visit_id, visitor_id, started_at, last_ping_at, "
                "active_seconds, pageviews, landing_path, ref_host) VALUES (?, ?, ?, ?, 0, 1, ?, ?)",
                (body.s, body.v, stamp, stamp, _clean_path(body.p), ref),
            )
        else:
            if visit["visitor_id"] != body.v:
                raise HTTPException(400, "Identificador inválido.")
            elapsed = (now - datetime.fromisoformat(visit["started_at"])).total_seconds()
            # Los segundos activos no pueden superar el tiempo real transcurrido (+ margen).
            active = max(visit["active_seconds"], min(body.a, int(elapsed) + 5))
            pageviews = visit["pageviews"] + (1 if body.e == "view" else 0)
            conn.execute(
                "UPDATE analytics_visit SET last_ping_at = ?, active_seconds = ?, pageviews = ? "
                "WHERE visit_id = ?",
                (stamp, active, min(pageviews, MAX_PAGEVIEWS_PER_VISIT), body.s),
            )
            conn.execute(
                "UPDATE analytics_visitor SET last_seen = ? WHERE visitor_id = ?", (stamp, body.v),
            )
        _maybe_purge(conn)
        conn.commit()
    finally:
        conn.close()
    return Response(status_code=204)


@router.post("/forget", status_code=204)
def forget(body: ForgetIn, request: Request) -> Response:
    check_same_origin(request)
    _check_ids(body.v)
    conn = _db()
    try:
        _ensure_schema(conn)
        conn.execute("DELETE FROM analytics_visit WHERE visitor_id = ?", (body.v,))
        conn.execute("DELETE FROM analytics_visitor WHERE visitor_id = ?", (body.v,))
        conn.commit()
    finally:
        conn.close()
    return Response(status_code=204)


class DayStatsOut(BaseModel):
    day: str
    visits: int
    visitors: int
    new_visitors: int
    returning_visitors: int
    pageviews: int
    avg_active_seconds: float


class RetentionOut(BaseModel):
    day: int
    eligible: int  # visitantes cuyo primer día fue hace al menos `day` días
    returned: int  # los que volvieron exactamente el día `day` después de su primera visita
    rate: float


class AnalyticsSummaryOut(BaseModel):
    generated_at: str
    total_visitors: int
    total_visits: int
    returning_visitors: int  # con 2 o más visitas
    median_active_seconds: float
    avg_active_seconds: float
    top_referrers: list[tuple[str, int]]
    days: list[DayStatsOut]
    retention: list[RetentionOut]


def build_summary(conn, days: int, now: datetime | None = None) -> AnalyticsSummaryOut:
    now = now or _now()
    today = now.date()
    visits = conn.execute(
        "SELECT visitor_id, substr(started_at, 1, 10) AS day, active_seconds, pageviews, ref_host "
        "FROM analytics_visit"
    ).fetchall()
    first_day = {
        r["visitor_id"]: r["first_seen"][:10]
        for r in conn.execute("SELECT visitor_id, first_seen FROM analytics_visitor")
    }
    visit_counts = {
        r["visitor_id"]: r["visit_count"]
        for r in conn.execute("SELECT visitor_id, visit_count FROM analytics_visitor")
    }

    by_day: dict[str, list] = {}
    visitor_days: dict[str, set[str]] = {}
    for r in visits:
        by_day.setdefault(r["day"], []).append(r)
        visitor_days.setdefault(r["visitor_id"], set()).add(r["day"])

    series = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        rows = by_day.get(day, [])
        visitors = {r["visitor_id"] for r in rows}
        new = {v for v in visitors if first_day.get(v) == day}
        seconds = [r["active_seconds"] for r in rows]
        series.append(DayStatsOut(
            day=day, visits=len(rows), visitors=len(visitors), new_visitors=len(new),
            returning_visitors=len(visitors) - len(new),
            pageviews=sum(r["pageviews"] for r in rows),
            avg_active_seconds=round(sum(seconds) / len(seconds), 1) if seconds else 0.0,
        ))

    retention = []
    for n in (1, 7, 30):
        eligible = returned = 0
        for visitor, first in first_day.items():
            if date_add(first, n) > today.isoformat():
                continue
            eligible += 1
            if date_add(first, n) in visitor_days.get(visitor, set()):
                returned += 1
        retention.append(RetentionOut(
            day=n, eligible=eligible, returned=returned,
            rate=round(returned / eligible, 4) if eligible else 0.0,
        ))

    seconds_all = [r["active_seconds"] for r in visits]
    refs: dict[str, int] = {}
    for r in visits:
        if r["ref_host"]:
            refs[r["ref_host"]] = refs.get(r["ref_host"], 0) + 1
    return AnalyticsSummaryOut(
        generated_at=_iso(now),
        total_visitors=len(first_day),
        total_visits=len(visits),
        returning_visitors=sum(1 for c in visit_counts.values() if c >= 2),
        median_active_seconds=float(median(seconds_all)) if seconds_all else 0.0,
        avg_active_seconds=round(sum(seconds_all) / len(seconds_all), 1) if seconds_all else 0.0,
        top_referrers=sorted(refs.items(), key=lambda kv: -kv[1])[:10],
        days=series,
        retention=retention,
    )


def date_add(day: str, n: int) -> str:
    return (datetime.fromisoformat(day) + timedelta(days=n)).date().isoformat()


@private_router.get("/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(days: int = 30):
    if days < 1 or days > 120:
        raise HTTPException(400, "days debe estar entre 1 y 120")
    conn = _db()
    try:
        _ensure_schema(conn)
        return build_summary(conn, days)
    finally:
        conn.close()
