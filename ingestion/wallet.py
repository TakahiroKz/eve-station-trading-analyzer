"""Obtiene el balance de ISK del wallet del personaje usando el refresh_token guardado.

Si no hay refresh_token (el usuario no corrió scripts/authorize.py todavía), degrada
devolviendo None — el llamador decide el fallback, nunca se bloquea el pipeline por esto.
"""
import logging
import os

from ingestion.esi_auth import get_wallet_balance
from ingestion.session import get_valid_session

logger = logging.getLogger(__name__)


def get_current_wallet_balance() -> float | None:
    session = get_valid_session()
    if session is None:
        return None
    access_token, character_id = session

    base_url = os.environ.get("ESI_BASE_URL", "https://esi.evetech.net/latest")
    try:
        return get_wallet_balance(base_url, access_token, character_id)
    except Exception:
        logger.exception("Fallo al obtener el balance del wallet; se usará el fallback fijo.")
        return None
