"""Ejecuta UNA VEZ para autorizar la app contra tu cuenta de EVE y guardar el refresh_token.

    python scripts/authorize.py

Abre tu navegador, inicia sesión con TU cuenta de EVE (esto lo haces tú, no el script),
autoriza el scope de wallet, y el script captura el callback local y guarda el
refresh_token en credentials/esi_refresh_token.txt (gitignored) para uso futuro sin
volver a pedir login.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from ingestion.esi_auth import (
    get_character_id,
    get_wallet_balance,
    run_authorization_flow,
    save_refresh_token,
)


def main() -> int:
    load_dotenv()
    client_id = os.environ["ESI_SSO_CLIENT_ID"]
    client_secret = os.environ["ESI_SSO_CLIENT_SECRET"]
    callback_url = os.environ.get("ESI_SSO_CALLBACK_URL", "http://localhost:8000/callback")
    scopes = os.environ.get("ESI_SSO_SCOPES", "esi-wallet.read_character_wallet.v1")
    base_url = os.environ.get("ESI_BASE_URL", "https://esi.evetech.net/latest")
    token_path = os.environ.get("ESI_REFRESH_TOKEN_PATH", "./credentials/esi_refresh_token.txt")

    tokens = run_authorization_flow(client_id, client_secret, callback_url, scopes)
    save_refresh_token(token_path, tokens["refresh_token"])

    character_id = get_character_id(tokens["access_token"])
    balance = get_wallet_balance(base_url, tokens["access_token"], character_id)

    print(f"\nAutorización OK. Personaje ID: {character_id}")
    print(f"Wallet actual: {balance:,.2f} ISK")
    print(f"Refresh token guardado en: {token_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
