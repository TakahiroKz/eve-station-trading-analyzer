"""Flujo OAuth2 (EVE SSO) para obtener y refrescar el token que lee el wallet del personaje.

El login real (usuario/contraseña de la cuenta EVE) lo hace el usuario en su propio
navegador — este módulo solo construye la URL de autorización, levanta un servidor
local que captura el `code` del callback, y lo intercambia por tokens.
"""
import base64
import logging
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

SSO_BASE_URL = "https://login.eveonline.com"
AUTHORIZE_PATH = "/v2/oauth/authorize"
TOKEN_PATH = "/v2/oauth/token"

logger = logging.getLogger(__name__)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_state = params.get("state", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<html><body><h3>Autorización recibida. Puedes cerrar esta pestaña.</h3></body></html>".encode("utf-8")
        )

    def log_message(self, format, *args):  # noqa: A002 - silenciar logs HTTP por línea
        pass


def build_authorize_url(client_id: str, callback_url: str, scopes: str, state: str) -> str:
    query = urlencode({
        "response_type": "code",
        "redirect_uri": callback_url,
        "client_id": client_id,
        "scope": scopes,
        "state": state,
    })
    return f"{SSO_BASE_URL}{AUTHORIZE_PATH}?{query}"


def run_authorization_flow(client_id: str, client_secret: str, callback_url: str, scopes: str,
                            open_browser: bool = True, timeout: float = 180.0) -> dict:
    """Levanta el servidor local, abre (o imprime) la URL de autorización, espera el
    callback y devuelve el token response (access_token, refresh_token, expires_in).
    """
    parsed_callback = urlparse(callback_url)
    port = parsed_callback.port or 8000

    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.auth_code = None
    server.auth_state = None
    server.timeout = timeout

    state = secrets.token_urlsafe(16)
    authorize_url = build_authorize_url(client_id, callback_url, scopes, state)

    print(f"\nAbre esta URL en tu navegador y autoriza con tu cuenta de EVE:\n{authorize_url}\n")
    if open_browser:
        webbrowser.open(authorize_url)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if server.auth_code is None:
        raise TimeoutError("No se recibió el callback de autorización a tiempo.")
    if server.auth_state != state:
        raise ValueError("El parámetro 'state' del callback no coincide (posible CSRF).")

    return exchange_code_for_token(client_id, client_secret, server.auth_code)


def _basic_auth_header(client_id: str, client_secret: str) -> dict:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}


def exchange_code_for_token(client_id: str, client_secret: str, code: str) -> dict:
    response = httpx.post(
        f"{SSO_BASE_URL}{TOKEN_PATH}",
        headers={**_basic_auth_header(client_id, client_secret),
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "authorization_code", "code": code},
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    response = httpx.post(
        f"{SSO_BASE_URL}{TOKEN_PATH}",
        headers={**_basic_auth_header(client_id, client_secret),
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


def save_refresh_token(path: str, refresh_token: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(refresh_token, encoding="utf-8")


def load_refresh_token(path: str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def get_character_id(access_token: str) -> int:
    """Decodifica el JWT del access_token para extraer el character_id (claim 'sub')."""
    import json

    payload_b64 = access_token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
    # claim 'sub' viene como "CHARACTER:EVE:<id>"
    return int(payload["sub"].split(":")[-1])


def get_wallet_balance(base_url: str, access_token: str, character_id: int) -> float:
    response = httpx.get(
        f"{base_url}/characters/{character_id}/wallet/",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )
    response.raise_for_status()
    return float(response.json())
