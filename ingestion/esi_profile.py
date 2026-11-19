"""Lectura del perfil de un jugador desde ESI: habilidades de comercio, standings relevantes y saldo del wallet.

Se pide solo lo mínimo y se guarda solo lo último (sin historial): 3 niveles de habilidad, los standings con las
facciones y corporaciones dueñas de las estaciones de referencia (finance/hubs.py) y el saldo. Sin reintentos largos:
corre dentro de una petición del usuario, así que ante un fallo de ESI se devuelve el estado y se conserva lo anterior.
"""
import logging
import os
import threading
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from finance.hubs import wanted_standing_ids
from ingestion import esi_auth
from storage import token_crypto, users_db

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://esi.evetech.net/latest"
SKILL_IDS = {3446: "broker_relations", 16597: "advanced_broker_relations", 16622: "accounting"}
SCOPE_SKILLS = "esi-skills.read_skills.v1"
SCOPE_STANDINGS = "esi-characters.read_standings.v1"
SCOPE_WALLET = "esi-wallet.read_character_wallet.v1"

REFRESH_AFTER = timedelta(hours=24)     # habilidades y standings se releen como mucho una vez al día
STALE_AFTER = timedelta(hours=48)       # pasado esto sin poder leer, se avisa de que el perfil puede estar desactualizado
WALLET_TTL = timedelta(minutes=5)
MIN_ATTEMPT_GAP = timedelta(minutes=5)  # entre dos intentos (con o sin éxito) de un mismo personaje
HTTP_TIMEOUT = 10.0

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


class EsiProfileError(Exception):
    """kind: REVOKED (el token ya no vale), SCOPE (falta un permiso) o UNAVAILABLE (ESI/SSO fallan)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _lock_for(character_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(character_id, threading.Lock())


def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json",
            "User-Agent": os.environ.get("ESI_USER_AGENT", "eve-market-screener")}


def _get(path: str, access_token: str):
    base = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    try:
        response = httpx.get(f"{base}{path}", headers=_headers(access_token), timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        raise EsiProfileError("UNAVAILABLE") from exc
    if response.status_code == 401:
        raise EsiProfileError("REVOKED")
    if response.status_code == 403:
        raise EsiProfileError("SCOPE")
    if response.status_code != 200:
        raise EsiProfileError("UNAVAILABLE")
    try:
        return response.json()
    except ValueError as exc:
        raise EsiProfileError("UNAVAILABLE") from exc


def refresh_access(client_id: str, secret: str, refresh_token: str) -> dict:
    try:
        return esi_auth.refresh_access_token(client_id, secret, refresh_token)
    except httpx.HTTPStatusError as exc:
        # invalid_grant = el jugador revocó el acceso o el token caducó; cualquier otra cosa es un fallo transitorio.
        if exc.response.status_code in (400, 401):
            try:
                if exc.response.json().get("error") == "invalid_grant":
                    raise EsiProfileError("REVOKED") from exc
            except ValueError:
                pass
        raise EsiProfileError("UNAVAILABLE") from exc
    except httpx.HTTPError as exc:
        raise EsiProfileError("UNAVAILABLE") from exc


def fetch_skills(access_token: str, character_id: int) -> dict[str, int]:
    data = _get(f"/characters/{character_id}/skills/", access_token)
    trained = {}
    for item in data.get("skills", []) if isinstance(data, dict) else []:
        name = SKILL_IDS.get(item.get("skill_id"))
        level = item.get("active_skill_level")
        if name and isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 5:
            trained[name] = level
    return {name: trained.get(name, 0) for name in SKILL_IDS.values()}   # una habilidad sin entrenar no aparece: nivel 0


def fetch_standings(access_token: str, character_id: int) -> dict[str, dict[str, str]]:
    """Solo los standings de las facciones y corporaciones de las estaciones de referencia; ausente en ESI = 0."""
    factions, corps = wanted_standing_ids()
    data = _get(f"/characters/{character_id}/standings/", access_token)
    out = {"faction": {str(i): "0" for i in factions}, "corp": {str(i): "0" for i in corps}}
    for item in data if isinstance(data, list) else []:
        kind = {"faction": "faction", "npc_corp": "corp"}.get(item.get("from_type"))
        ident = item.get("from_id")
        if kind and str(ident) in out[kind]:
            try:
                value = Decimal(str(item.get("standing")))
            except InvalidOperation:
                continue
            if value.is_finite() and abs(value) <= 10:
                out[kind][str(ident)] = format(value.quantize(Decimal("0.0001")).normalize(), "f")
    return out


def fetch_wallet(access_token: str, character_id: int) -> str:
    balance = _get(f"/characters/{character_id}/wallet/", access_token)
    if isinstance(balance, bool) or not isinstance(balance, (int, float)):
        raise EsiProfileError("UNAVAILABLE")
    value = Decimal(str(balance))
    if not value.is_finite() or value < 0:
        raise EsiProfileError("UNAVAILABLE")
    return format(value.quantize(Decimal("0.01")), "f")


def _age(stamp: str | None, now: datetime) -> timedelta | None:
    if not stamp:
        return None
    return now - datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=now.tzinfo)


def needs_sync(profile, now: datetime, want_wallet: bool = False) -> bool:
    if profile is None or profile["skills_at"] is None or profile["standings_at"] is None:
        return True
    if (_age(profile["skills_at"], now) or timedelta(0)) >= REFRESH_AFTER:
        return True
    if (_age(profile["standings_at"], now) or timedelta(0)) >= REFRESH_AFTER:
        return True
    return want_wallet and (profile["wallet_at"] is None or _age(profile["wallet_at"], now) >= WALLET_TTL)


def is_stale(profile, now: datetime) -> bool:
    """True si lo último que se leyó de ESI es de hace más de 48 h (no se pudo actualizar)."""
    if profile is None or profile["skills_at"] is None:
        return False
    return (_age(profile["skills_at"], now) or timedelta(0)) >= STALE_AFTER


def sync_profile(conn, character_id: int, client_id: str, secret: str, now: datetime, *, force: bool = False,
                 want_wallet: bool = False) -> str:
    """Actualiza lo que toque y devuelve el estado: OK, PARTIAL (faltan permisos), REVOKED, UNAVAILABLE,
    THROTTLED (demasiado pronto desde el último intento; no se tocó nada) o NOT_NEEDED."""
    with _lock_for(character_id):
        profile = users_db.get_profile(conn, character_id)
        if not force and not needs_sync(profile, now, want_wallet):
            return "NOT_NEEDED"
        gap = _age(profile["last_attempt_at"], now) if profile else None
        if gap is not None and gap < MIN_ATTEMPT_GAP:
            return "THROTTLED"
        token = users_db.get_token(conn, character_id)
        if token is None or token["status"] != "ACTIVE":
            users_db.save_sync_result(conn, character_id, "REVOKED", now)
            conn.commit()
            return "REVOKED"
        do_wallet = want_wallet and (force or profile is None or profile["wallet_at"] is None
                                     or (_age(profile["wallet_at"], now) or timedelta(0)) >= WALLET_TTL)
        do_profile = force or needs_sync(profile, now, False)
        scopes = set(token["scopes"].split())
        status = "OK"
        try:
            refresh = token_crypto.decrypt(bytes(token["refresh_token_enc"]), character_id)
            tokens = refresh_access(client_id, secret, refresh)
            access = tokens["access_token"]
            new_refresh = tokens.get("refresh_token")
            if new_refresh and new_refresh != refresh:           # CCP puede rotar el refresh token: guardar el nuevo
                users_db.save_token(conn, character_id, token_crypto.encrypt(new_refresh, character_id),
                                    token["scopes"], now)
            if do_profile:
                if SCOPE_SKILLS in scopes:
                    users_db.save_skills(conn, character_id, fetch_skills(access, character_id), now)
                else:
                    status = "PARTIAL"
                if SCOPE_STANDINGS in scopes:
                    users_db.save_standings(conn, character_id, fetch_standings(access, character_id), now)
                else:
                    status = "PARTIAL"
            if do_wallet:
                if SCOPE_WALLET in scopes:
                    users_db.save_wallet(conn, character_id, fetch_wallet(access, character_id), now)
                else:
                    status = "PARTIAL"
        except EsiProfileError as exc:
            status = exc.kind if exc.kind != "SCOPE" else "PARTIAL"
            if exc.kind == "REVOKED":
                users_db.set_token_status(conn, character_id, "REVOKED", now)
        except (token_crypto.CryptoError, KeyError, TypeError):
            logger.warning("No se pudo preparar el token de un personaje para leer ESI")
            status = "UNAVAILABLE"
        users_db.save_sync_result(conn, character_id, status, now)
        conn.commit()
        return status
