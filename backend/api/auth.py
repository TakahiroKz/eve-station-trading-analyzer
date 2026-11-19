"""Cuentas de visitantes con EVE SSO (rutas públicas /api/auth/*, fuera de Cloudflare Access).

Apagado por defecto: solo se activa cuando están configuradas EVE_LOGIN_CLIENT_ID, EVE_LOGIN_CLIENT_SECRET y
USERS_ENC_KEYS. Sin eso, /status dice enabled=false y el resto responde 503 (el sitio sigue funcionando igual).
Datos y decisiones: docs/ANALISIS_CUENTAS_Y_BASE_DE_DATOS.md.
"""
import hmac
import logging
import os
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from backend.api.security import check_same_origin
from ingestion import esi_auth
from ingestion.eve_login import REQUIRED_SCOPES, LoginError, verify_access_token
from storage import token_crypto, users_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

CONSENT_VERSION = "2026-11-20"           # sube cuando cambie la lista de datos o su uso (pide consentir de nuevo)
SESSION_COOKIE = "eve_session"
STATE_COOKIE = "eve_oauth"
STATE_TTL = 600
DEFAULT_CALLBACK = "https://evemarket-analyzer.online/api/auth/callback"
NO_STORE = {"Cache-Control": "no-store"}


def _config() -> tuple[str, str, str] | None:
    client_id = os.environ.get("EVE_LOGIN_CLIENT_ID", "").strip()
    secret = os.environ.get("EVE_LOGIN_CLIENT_SECRET", "").strip()
    if not (client_id and secret and token_crypto.keys_configured()):
        return None
    return client_id, secret, os.environ.get("EVE_LOGIN_CALLBACK_URL", DEFAULT_CALLBACK).strip()


def _require_config() -> tuple[str, str, str]:
    cfg = _config()
    if cfg is None:
        raise HTTPException(503, "El inicio de sesión no está disponible.", headers=NO_STORE)
    return cfg


def _secure(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def _json(payload: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=NO_STORE)


def _redirect(request: Request, flag: str) -> RedirectResponse:
    response = RedirectResponse(f"/?login={flag}", status_code=303, headers=NO_STORE)
    response.delete_cookie(STATE_COOKIE, path="/api/auth")
    return response


def _current_user(conn, request: Request):
    return users_db.get_session_user(conn, request.cookies.get(SESSION_COOKIE), users_db.utcnow())


@router.get("/status")
def status(request: Request):
    if _config() is None:
        return _json({"enabled": False, "authenticated": False, "character": None, "consent_version": CONSENT_VERSION})
    conn = users_db.connect()
    try:
        user = _current_user(conn, request)
    finally:
        conn.close()
    return _json({
        "enabled": True, "authenticated": user is not None, "consent_version": CONSENT_VERSION,
        "needs_consent": bool(user and user["consent_version"] != CONSENT_VERSION),
        "character": {"id": user["character_id"], "name": user["name"]} if user else None})


@router.get("/login")
def login(request: Request, consent: str = ""):
    client_id, _secret, callback = _require_config()
    if consent != CONSENT_VERSION:
        raise HTTPException(400, "Falta el consentimiento vigente.", headers=NO_STORE)
    state = secrets.token_urlsafe(24)
    url = esi_auth.build_authorize_url(client_id, callback, " ".join(REQUIRED_SCOPES), state)
    response = RedirectResponse(url, status_code=302, headers=NO_STORE)
    response.set_cookie(STATE_COOKIE, state, max_age=STATE_TTL, httponly=True, secure=_secure(request),
                        samesite="lax", path="/api/auth")
    return response


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    client_id, secret, _cb = _require_config()
    expected = request.cookies.get(STATE_COOKIE, "")
    if error:
        return _redirect(request, "denied")
    if not (code and state and expected) or not hmac.compare_digest(state, expected):
        return _redirect(request, "error")          # sin state válido no se toca nada (login CSRF)
    try:
        tokens = esi_auth.exchange_code_for_token(client_id, secret, code)
        character_id, name, scopes = verify_access_token(tokens["access_token"], client_id)
        refresh = tokens["refresh_token"]
        encrypted = token_crypto.encrypt(refresh, character_id)
    except (LoginError, httpx.HTTPError, KeyError, token_crypto.CryptoError) as exc:
        logger.warning("Inicio de sesión rechazado: %s", type(exc).__name__)   # nunca se registran tokens ni códigos
        return _redirect(request, "error")
    now = users_db.utcnow()
    conn = users_db.connect()
    try:
        users_db.upsert_user(conn, character_id, name or f"Character {character_id}", CONSENT_VERSION, now)
        users_db.save_token(conn, character_id, encrypted, " ".join(scopes), now)
        raw = users_db.create_session(conn, character_id, now)
        users_db.purge_expired_sessions(conn, now)
        conn.commit()
    finally:
        conn.close()
    response = _redirect(request, "ok")
    response.set_cookie(SESSION_COOKIE, raw, max_age=users_db.SESSION_TTL_DAYS * 86400, httponly=True,
                        secure=_secure(request), samesite="lax", path="/")
    return response


@router.post("/logout")
def logout(request: Request):
    check_same_origin(request)
    raw = request.cookies.get(SESSION_COOKIE)
    if _config() is not None and raw:
        conn = users_db.connect()
        try:
            user = _current_user(conn, request)
            users_db.delete_session(conn, raw)
            if user:
                users_db.delete_token(conn, user["character_id"])   # cerrar sesión retira también el acceso a ESI
            conn.commit()
        finally:
            conn.close()
    response = _json({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.delete("/me")
def delete_me(request: Request):
    check_same_origin(request)
    _require_config()
    conn = users_db.connect()
    try:
        user = _current_user(conn, request)
        if user is None:
            raise HTTPException(401, "No has iniciado sesión.", headers=NO_STORE)
        users_db.delete_user(conn, user["character_id"])
        conn.commit()
    finally:
        conn.close()
    response = _json({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me/export")
def export_me(request: Request):
    _require_config()
    conn = users_db.connect()
    try:
        user = _current_user(conn, request)
        if user is None:
            raise HTTPException(401, "No has iniciado sesión.", headers=NO_STORE)
        data = users_db.export_user(conn, user["character_id"])
    finally:
        conn.close()
    return _json(data)
