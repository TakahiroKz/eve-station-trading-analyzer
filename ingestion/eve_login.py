"""Inicio de sesión de visitantes con EVE SSO v2: verificación del access token con las claves públicas de CCP.

El character_id sale SOLO de un JWT firmado por CCP (RS256), con audiencia = nuestro client_id; nunca de un
parámetro que mande el navegador.
"""
import threading
import time

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

JWKS_URL = "https://login.eveonline.com/oauth/jwks"
ISSUERS = ["login.eveonline.com", "https://login.eveonline.com"]
REQUIRED_SCOPES = ("esi-skills.read_skills.v1", "esi-characters.read_standings.v1",
                   "esi-wallet.read_character_wallet.v1")
_TTL = 3600.0
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "jwks": None}


class LoginError(Exception):
    """El token no es válido (firma, caducidad, audiencia, emisor o forma)."""


def fetch_jwks() -> dict:
    with _lock:
        if _cache["jwks"] is not None and time.monotonic() - _cache["at"] < _TTL:
            return _cache["jwks"]
        response = httpx.get(JWKS_URL, timeout=10.0)
        response.raise_for_status()
        _cache.update(at=time.monotonic(), jwks=response.json())
        return _cache["jwks"]


def verify_access_token(token: str, client_id: str, jwks: dict | None = None) -> tuple[int, str, list[str]]:
    """Devuelve (character_id, nombre, scopes concedidos) o lanza LoginError."""
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise LoginError("algoritmo no permitido")
        keys = (jwks or fetch_jwks()).get("keys", [])
        match = [k for k in keys if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"]
        if not match:
            raise LoginError("clave de firma desconocida")
        claims = jwt.decode(token, RSAAlgorithm.from_jwk(match[0]), algorithms=["RS256"], audience=client_id,
                            issuer=ISSUERS, options={"require": ["exp", "iss", "aud", "sub"]})
        subject = str(claims["sub"]).split(":")
        if len(subject) != 3 or subject[:2] != ["CHARACTER", "EVE"] or not subject[2].isdigit():
            raise LoginError("sujeto inesperado")
        name = str(claims.get("name") or "")[:100]
        scopes = claims.get("scp") or []
        scopes = [scopes] if isinstance(scopes, str) else [str(s) for s in scopes]
        return int(subject[2]), name, scopes
    except LoginError:
        raise
    except (jwt.PyJWTError, ValueError, KeyError, httpx.HTTPError) as exc:
        raise LoginError(type(exc).__name__) from exc
