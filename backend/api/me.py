"""Perfil y capital del jugador con sesión (rutas /api/me/*, fuera de Cloudflare Access; requieren la cookie de sesión).

Habilidades y standings se leen de ESI al entrar y una vez al día; el jugador puede corregirlos a mano y cada dato dice
de dónde sale (ESI / MANUAL / DEFAULT). El saldo del wallet se lee solo cuando se pide y se guarda 5 minutos.
Datos y decisiones: docs/ANALISIS_CUENTAS_Y_BASE_DE_DATOS.md.
"""
import json
import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.api.auth import CONSENT_VERSION, NO_STORE, _current_user, _require_config
from backend.api.security import check_same_origin
from finance.hubs import HUB_BY_MARKET, HUBS
from finance.user_profile import SKILL_FIELDS, build_profile, fee_summary
from ingestion import esi_profile
from storage import users_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/me", tags=["me"])
NOTE_STANDINGS = ("Los standings son los que devuelve ESI; compáralos con los que ves en el juego y corrígelos a mano si "
                  "difieren (si ESI ya incluye las habilidades Connections/Diplomacy no hace falta ajustar nada).")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillsIn(_Strict):
    broker_relations: int | None = Field(None, ge=0, le=5)
    advanced_broker_relations: int | None = Field(None, ge=0, le=5)
    accounting: int | None = Field(None, ge=0, le=5)


class StandingIn(_Strict):
    faction: float | None = Field(None, ge=-10, le=10, allow_inf_nan=False)
    corp: float | None = Field(None, ge=-10, le=10, allow_inf_nan=False)


class OverrideIn(_Strict):
    skills: SkillsIn = SkillsIn()
    standings: dict[str, StandingIn] = {}


def _json(payload: dict, status: int = 200, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={**NO_STORE, **(headers or {})})


def _session(request: Request):
    """(conn, user) de la sesión; 401 sin sesión, 403 si falta el consentimiento vigente."""
    client_id, secret, _cb = _require_config()
    conn = users_db.connect()
    user = _current_user(conn, request)
    if user is None:
        conn.close()
        raise HTTPException(401, "No has iniciado sesión.", headers=NO_STORE)
    if user["consent_version"] != CONSENT_VERSION:
        conn.close()
        raise HTTPException(403, "Hay que consentir de nuevo.", headers=NO_STORE)
    return conn, user, client_id, secret


def _loads(raw: str | None) -> dict | None:
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _sync_label(profile, token, now) -> dict:
    scopes = set((token["scopes"] if token else "").split())
    required = {esi_profile.SCOPE_SKILLS, esi_profile.SCOPE_STANDINGS, esi_profile.SCOPE_WALLET}
    status = profile["sync_status"] if profile else "NEVER"
    if token is not None and token["status"] == "REVOKED":
        status = "REVOKED"
    return {"status": status, "skills_at": profile["skills_at"] if profile else None,
            "standings_at": profile["standings_at"] if profile else None,
            "stale": esi_profile.is_stale(profile, now), "missing_scopes": sorted(required - scopes)}


def _profile_payload(conn, user, now) -> dict:
    cid = user["character_id"]
    profile = users_db.get_profile(conn, cid)
    token = users_db.get_token(conn, cid)
    skills_esi = _loads(profile["skills_json"]) if profile else None
    standings_esi = _loads(profile["standings_json"]) if profile else None
    override = (_loads(profile["override_json"]) if profile else None) or {}
    markets = []
    skills_out = None
    for hub in HUBS:
        built, skills, standings = build_profile(hub, skills_esi, standings_esi, override)
        skills_out = skills_out or skills
        markets.append({
            "market_id": hub.market_id, "name": hub.name, "station": hub.station_name, "owner": hub.owner_corp_name,
            "standings": {k: {"value": float(v["value"]), "source": v["source"],
                              "esi": float(v["esi"]) if v["esi"] is not None else None} for k, v in standings.items()},
            "fees": {**fee_summary(built), "source": built.source}})
    return {"character": {"id": cid, "name": user["name"]}, "sync": _sync_label(profile, token, now),
            "skills": skills_out, "markets": markets, "has_override": bool(override), "note": NOTE_STANDINGS}


@router.get("/profile")
def get_profile(request: Request):
    conn, user, client_id, secret = _session(request)
    try:
        now = users_db.utcnow()
        esi_profile.sync_profile(conn, user["character_id"], client_id, secret, now)   # solo si toca (1 vez al día)
        return _json(_profile_payload(conn, user, now))
    finally:
        conn.close()


@router.post("/profile/refresh")
def refresh_profile(request: Request):
    check_same_origin(request)
    conn, user, client_id, secret = _session(request)
    try:
        now = users_db.utcnow()
        status = esi_profile.sync_profile(conn, user["character_id"], client_id, secret, now, force=True)
        if status == "THROTTLED":
            raise HTTPException(429, "Espera unos minutos antes de volver a actualizar.",
                                headers={**NO_STORE, "Retry-After": str(int(esi_profile.MIN_ATTEMPT_GAP.total_seconds()))})
        return _json(_profile_payload(conn, user, now))
    finally:
        conn.close()


@router.put("/profile/override")
def put_override(body: OverrideIn, request: Request):
    """Sustituye todas las correcciones manuales; lo que no se envía (o va null) vuelve al dato de ESI."""
    check_same_origin(request)
    conn, user, _client_id, _secret = _session(request)
    try:
        skills = {k: v for k, v in body.skills.model_dump().items() if v is not None and k in SKILL_FIELDS}
        standings = {}
        for market_id, values in body.standings.items():
            if market_id not in HUB_BY_MARKET:
                raise HTTPException(422, f"Mercado desconocido: {market_id}", headers=NO_STORE)
            cleaned = {k: format(Decimal(str(v)), "f") for k, v in values.model_dump().items() if v is not None}
            if cleaned:
                standings[market_id] = cleaned
        override = {}
        if skills:
            override["skills"] = skills
        if standings:
            override["standings"] = standings
        users_db.save_override(conn, user["character_id"], override or None)
        conn.commit()
        return _json(_profile_payload(conn, user, users_db.utcnow()))
    finally:
        conn.close()


@router.get("/capital")
def get_capital(request: Request):
    """Saldo del wallet (caché de 5 min); el jugador lo ve solo cuando abre su perfil."""
    conn, user, client_id, secret = _session(request)
    try:
        now = users_db.utcnow()
        esi_profile.sync_profile(conn, user["character_id"], client_id, secret, now, want_wallet=True)
        profile = users_db.get_profile(conn, user["character_id"])
        token = users_db.get_token(conn, user["character_id"])
        isk = profile["wallet_isk"] if profile else None
        return _json({"wallet_isk": isk, "wallet_at": profile["wallet_at"] if profile else None,
                      "sync": _sync_label(profile, token, now)})
    finally:
        conn.close()
