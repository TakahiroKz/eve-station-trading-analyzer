"""Endurecimiento de SEO a nivel de aplicación (SEO): redirecciones
canónicas, cabeceras de caché y de indexación, y la documentación interactiva apagada.

Cloudflare termina el TLS y entrega las requests por el túnel con `X-Forwarded-Proto`; el
token de la API de Cloudflare de este proyecto no puede cambiar ajustes de zona, así que
las redirecciones se resuelven acá en vez de con "Always Use HTTPS" / una Redirect Rule.
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from backend.api.security import apply_security_headers

CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "evemarket-analyzer.online")

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
PUBLIC_API_CACHE = "public, max-age=30"
LANGUAGE_ROOTS = ("/es", "/de", "/fr", "/it")  # per-language home pages built by the frontend


def docs_kwargs() -> dict:
    """La documentación (/docs, /redoc, /openapi.json) también lista las rutas privadas y
    no aporta nada a un visitante: solo se publica con ENABLE_API_DOCS=1 (dev local)."""
    if os.environ.get("ENABLE_API_DOCS") == "1":
        return {}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def canonical_redirect(host: str, forwarded_proto: str, path_qs: str) -> str | None:
    """URL a la que redirigir (301), o None si la request ya es canónica. Solo actúa sobre
    el dominio de producción (y su `www`): localhost, el health check del deploy y los
    tests no mandan ese Host y no se tocan."""
    host = host.split(":")[0].lower()
    if host not in (CANONICAL_HOST, f"www.{CANONICAL_HOST}"):
        return None
    # /es -> /es/: the per-language pages are directories; StaticFiles would answer 307 with
    # an http:// Location (it only sees the tunnel's plain HTTP), costing a second redirect.
    path, sep, query = path_qs.partition("?")
    fixed_path = f"{path}/" if path in LANGUAGE_ROOTS else path
    fixed = f"{fixed_path}{sep}{query}"
    if host == CANONICAL_HOST and forwarded_proto != "http" and fixed == path_qs:
        return None
    return f"https://{CANONICAL_HOST}{fixed}"


def cache_control_for(path: str, content_type: str, status_code: int) -> str | None:
    if status_code != 200:
        return None
    if path.startswith("/assets/"):
        return IMMUTABLE_CACHE  # archivos con hash en el nombre: nunca cambian
    if path.startswith("/api/") and not path.startswith("/api/private")             and content_type.startswith("application/json"):
        return PUBLIC_API_CACHE  # datos que el motor renueva cada 4 h; frena a quien repite pedidos
    if content_type.startswith("text/html"):
        return "no-cache"  # que el HTML siempre apunte a los assets vigentes
    return None


def install_seo_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def seo_middleware(request: Request, call_next) -> Response:
        target = canonical_redirect(
            request.headers.get("host", ""),
            request.headers.get("x-forwarded-proto", ""),
            request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        )
        if target:
            return RedirectResponse(target, status_code=301)

        # Los monitores (UptimeRobot) y algunos rastreadores usan HEAD; las rutas de la API solo
        # declaran GET y el mount estático respondía 404. Se atiende como GET y se descarta el cuerpo.
        is_head = request.method == "HEAD"
        if is_head:
            request.scope["method"] = "GET"

        response = await call_next(request)
        cache = cache_control_for(
            request.url.path, response.headers.get("content-type", ""), response.status_code,
        )
        if cache and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = cache
        apply_security_headers(response.headers, request.headers.get("x-forwarded-proto", ""))
        if request.url.path.startswith("/api/"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if is_head:
            return Response(status_code=response.status_code, headers=dict(response.headers))
        return response
