"""Endurecimiento de seguridad de la API (auditoría del 2026-11-04): cabeceras de
seguridad, defensa contra CSRF en las rutas que escriben y verificación real de la
sesión de Cloudflare Access.

Cloudflare Access protege /api/private en el borde, pero el chequeo que tenía la app solo
miraba que existiera un header con forma de JWT, sin verificarlo: cualquiera que llegara al
origen sin pasar por Access lo falsificaba con `a.b.c`. Con CF_ACCESS_AUD configurado
(el "Application Audience (AUD) Tag" de la Access Application) la app verifica la firma
RS256, la expiración y la audiencia contra las claves públicas de Cloudflare.
"""
import logging
import os
import threading
import time
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, Request
from google.auth import jwt as google_jwt



logger = logging.getLogger(__name__)

CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "evemarket-analyzer.online")

# Sin scripts inline ni orígenes externos: la PWA, las páginas de ítem y las de idioma se
# sirven con JS/CSS/fuentes propios. 'unsafe-inline' solo en estilos (React usa style=...
# y las páginas de ítem llevan un <style>).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; manifest-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
HSTS = "max-age=31536000"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_ORIGIN_HOSTS = {CANONICAL_HOST, f"www.{CANONICAL_HOST}", "localhost", "127.0.0.1"}

_CERTS_TTL = 3600.0
_certs_lock = threading.Lock()
_certs_cache: dict[str, tuple[float, dict[str, str]]] = {}


def apply_security_headers(headers, forwarded_proto: str) -> None:
    for name, value in SECURITY_HEADERS.items():
        if name not in headers:
            headers[name] = value
    if forwarded_proto == "https" and "strict-transport-security" not in headers:
        headers["Strict-Transport-Security"] = HSTS


def check_same_origin(request: Request) -> None:
    """Las rutas que modifican estado usan la cookie de Access, que el navegador manda sola:
    un sitio ajeno podría disparar un POST (p. ej. resetear los ajustes). Se rechazan los
    pedidos de navegador con origen ajeno; curl y similares no mandan Origin y pasan."""
    if request.method in SAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Origen no permitido.")
    origin = request.headers.get("origin")
    if origin and (urlparse(origin).hostname or "") not in ALLOWED_ORIGIN_HOSTS:
        raise HTTPException(403, "Origen no permitido.")


def _access_certs(team_url: str) -> dict[str, str]:
    now = time.monotonic()
    with _certs_lock:
        cached = _certs_cache.get(team_url)
        if cached and now - cached[0] < _CERTS_TTL:
            return cached[1]
    try:
        response = httpx.get(f"{team_url}/cdn-cgi/access/certs", timeout=5.0)
        response.raise_for_status()
        certs = {c["kid"]: c["cert"] for c in response.json().get("public_certs", [])}
    except Exception:
        if cached:  # si Cloudflare no responde, mejor las claves viejas que dejar a todos fuera
            logger.warning("No se pudieron renovar las claves de Access; se usan las anteriores.")
            return cached[1]
        raise
    with _certs_lock:
        _certs_cache[team_url] = (now, certs)
    return certs


def _issuer_team_url(claims_iss: str) -> str | None:
    configured = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
    if configured:
        configured = configured if configured.startswith("https://") else f"https://{configured}"
        return configured if claims_iss == configured else None
    parsed = urlparse(claims_iss)
    if parsed.scheme == "https" and (parsed.hostname or "").endswith(".cloudflareaccess.com"):
        return f"https://{parsed.hostname}"
    return None


def verify_access_jwt(token: str) -> None:
    """No hace nada si CF_ACCESS_AUD no está configurado. Con CF_ACCESS_ENFORCE=0 verifica y
    deja el fallo en el log sin bloquear (para validar la configuración antes de exigirla)."""
    audience = os.environ.get("CF_ACCESS_AUD", "").strip()
    if not audience:
        return
    enforce = os.environ.get("CF_ACCESS_ENFORCE", "1") != "0"
    try:
        claims = google_jwt.decode(token, verify=False, audience=None)
        team_url = _issuer_team_url(str(claims.get("iss", "")))
        if team_url is None:
            raise ValueError("emisor del token no reconocido")
        # Cloudflare manda `aud` como lista y google-auth solo compara strings: la audiencia
        # se comprueba a mano; firma y expiración las verifica la librería.
        verified = google_jwt.decode(
            token, certs=_access_certs(team_url), audience=None, clock_skew_in_seconds=60,
        )
        token_aud = verified.get("aud")
        token_aud = [token_aud] if isinstance(token_aud, str) else list(token_aud or [])
        if audience not in token_aud:
            raise ValueError("audiencia del token no coincide")
    except Exception as exc:
        logger.warning("Sesión de Cloudflare Access NO verificada (%s)%s", type(exc).__name__,
                       "" if enforce else " — modo observación, se permite")
        if enforce:
            raise HTTPException(401, "Acceso restringido (sesión de Cloudflare Access no válida).") from exc
