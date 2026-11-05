"""Límite de peticiones por IP para /api/* (A04 de la auditoría OWASP). Ventana deslizante
en memoria, por proceso: el sitio corre en un solo contenedor uvicorn, así que alcanza.

La IP real llega en `CF-Connecting-IP` (el puerto 8001 solo es alcanzable por el túnel de
Cloudflare, que siempre la pone); sin esa cabecera se usa la IP del socket.
RATE_LIMIT_PER_MIN=0 lo apaga (tests, desarrollo local).
"""
import os
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DEFAULT_PER_MINUTE = 120
WINDOW_SECONDS = 60.0
MAX_TRACKED_IPS = 10_000

_hits: dict[str, deque] = {}


def _limit() -> int:
    try:
        return int(os.environ.get("RATE_LIMIT_PER_MIN", DEFAULT_PER_MINUTE))
    except ValueError:
        return DEFAULT_PER_MINUTE


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def check_rate_limit(ip: str, limit: int, now: float | None = None) -> int | None:
    """None si la petición pasa; si no, los segundos que faltan para que se libere un cupo."""
    now = time.monotonic() if now is None else now
    if len(_hits) > MAX_TRACKED_IPS:
        for key in [k for k, q in _hits.items() if not q or now - q[-1] > WINDOW_SECONDS]:
            del _hits[key]
    queue = _hits.setdefault(ip, deque())
    while queue and now - queue[0] > WINDOW_SECONDS:
        queue.popleft()
    if len(queue) >= limit:
        return max(1, int(WINDOW_SECONDS - (now - queue[0])) + 1)
    queue.append(now)
    return None


def reset() -> None:
    _hits.clear()


def install_rate_limit(app: FastAPI) -> None:
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        limit = _limit()
        if limit > 0 and request.url.path.startswith("/api/"):
            retry_after = check_rate_limit(client_ip(request), limit)
            if retry_after is not None:
                return JSONResponse(
                    {"detail": "Demasiadas peticiones. Probá de nuevo en unos segundos."},
                    status_code=429, headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)
