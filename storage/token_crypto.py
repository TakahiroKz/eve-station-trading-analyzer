"""Cifrado en reposo de los refresh tokens de los usuarios (AES-256-GCM, claves rotables).

Formato del blob: 0x01 | kid (4 bytes = sha256(clave)[:4]) | nonce (12) | texto cifrado + etiqueta.
El character_id va como dato asociado (AAD): un blob copiado a la fila de otro personaje no descifra.
USERS_ENC_KEYS = claves urlsafe-base64 de 32 bytes separadas por comas; la primera cifra, todas descifran
(así se rota: se antepone una clave nueva y se re-cifra con scripts/users_admin.py rotate).
"""
import base64
import hashlib
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"\x01"


class CryptoError(Exception):
    """Configuración de claves ausente/inválida o blob que no descifra (sin detalles sensibles)."""


def generate_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def _parse_keys(raw: str | None = None) -> list[tuple[bytes, bytes]]:
    raw = os.environ.get("USERS_ENC_KEYS", "") if raw is None else raw
    keys = []
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        try:
            key = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
        except ValueError as exc:
            raise CryptoError("USERS_ENC_KEYS contiene una clave que no es base64") from exc
        if len(key) != 32:
            raise CryptoError("cada clave de USERS_ENC_KEYS debe tener 32 bytes")
        keys.append((hashlib.sha256(key).digest()[:4], key))
    if not keys:
        raise CryptoError("USERS_ENC_KEYS no está configurada")
    return keys


def keys_configured() -> bool:
    try:
        _parse_keys()
    except CryptoError:
        return False
    return True


def encrypt(plaintext: str, character_id: int, keys_raw: str | None = None) -> bytes:
    kid, key = _parse_keys(keys_raw)[0]
    nonce = secrets.token_bytes(12)
    return VERSION + kid + nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), str(character_id).encode())


def decrypt(blob: bytes, character_id: int, keys_raw: str | None = None) -> str:
    if len(blob) < 1 + 4 + 12 + 16 or blob[:1] != VERSION:
        raise CryptoError("blob con formato desconocido")
    kid, nonce, body = blob[1:5], blob[5:17], blob[17:]
    for known_kid, key in _parse_keys(keys_raw):
        if known_kid == kid:
            try:
                return AESGCM(key).decrypt(nonce, body, str(character_id).encode()).decode("utf-8")
            except InvalidTag as exc:
                raise CryptoError("el blob no descifra (clave o personaje incorrectos)") from exc
    raise CryptoError("la clave de este blob ya no está en USERS_ENC_KEYS")


def needs_rotation(blob: bytes, keys_raw: str | None = None) -> bool:
    """True si el blob no está cifrado con la clave actual (la primera)."""
    return blob[1:5] != _parse_keys(keys_raw)[0][0]
