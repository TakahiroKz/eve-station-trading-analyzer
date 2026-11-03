"""Sesión ESI autenticada (access_token + character_id) a partir del refresh_token
guardado por scripts/authorize.py. Compartida por wallet.py, character_orders.py y el
endpoint de la API que abre ventanas en el cliente — todos degradan a None si el
usuario todavía no autorizó, sin bloquear el pipeline.
"""
import logging
import os

from ingestion.esi_auth import get_character_id, load_refresh_token, refresh_access_token

logger = logging.getLogger(__name__)


def get_valid_session() -> tuple[str, int] | None:
    """Devuelve (access_token, character_id) frescos, o None si no hay autorización."""
    client_id = os.environ.get("ESI_SSO_CLIENT_ID")
    client_secret = os.environ.get("ESI_SSO_CLIENT_SECRET")
    token_path = os.environ.get("ESI_REFRESH_TOKEN_PATH", "./credentials/esi_refresh_token.txt")

    if not client_id or not client_secret:
        logger.warning("ESI_SSO_CLIENT_ID/SECRET no configurados; sin sesión autenticada.")
        return None

    refresh_token = load_refresh_token(token_path)
    if refresh_token is None:
        logger.warning(
            "No hay refresh_token guardado. Corre 'python scripts/authorize.py' una vez para autorizar."
        )
        return None

    try:
        tokens = refresh_access_token(client_id, client_secret, refresh_token)
        character_id = get_character_id(tokens["access_token"])
        return tokens["access_token"], character_id
    except Exception:
        logger.exception("Fallo al refrescar la sesión ESI.")
        return None
