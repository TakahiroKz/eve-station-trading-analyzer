"""Rutas privadas: datos y acciones que no deben quedar visibles/accionables para
un visitante anónimo (wallet, órdenes propias, ajustes de los motores). Montadas
bajo /api/private, el único prefijo que la Cloudflare Access Application protege en
el borde — más el chequeo liviano de deps.require_cf_access_header
como red de seguridad adicional. Nada de auth propia acá: la autenticación en sí la
resuelve Cloudflare antes de que la request llegue a este proceso."""
import logging
import math
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from analytics.eve_calculator import (
    EveCalculatorConfig,
    config_from_settings,
    evaluar_oportunidad,
    resolve_volumen_deseado,
)
from backend.api.deps import ITEM_JOIN, ITEM_SELECT_COLS, _db, require_cf_access_header
from backend.api.schemas import (
    AppSettingOut,
    AppSettingUpdateIn,
    AuthPingOut,
    CharacterOrderClosedOut,
    CharacterOrderFillOut,
    CharacterOrderOut,
    OpenWindowOut,
    OpportunityOut,
    WalletOut,
)
from ingestion.esi_client import DEFAULT_BASE_URL, EsiClient
from ingestion.session import get_valid_session
from ingestion.wallet import get_current_wallet_balance
from scheduler.orders_run import check_character_orders
from storage.db import get_app_settings, get_app_settings_dict, reset_app_settings, update_app_setting
from storage.settings_registry import SETTINGS_BY_KEY, STRICTLY_POSITIVE_KEYS

router = APIRouter(prefix="/api/private", dependencies=[Depends(require_cf_access_header)])
logger = logging.getLogger(__name__)


def _check_limit(limit: int) -> None:
    if limit < 1 or limit > 500:
        raise HTTPException(400, "limit debe estar entre 1 y 500")


@router.get("/auth/ping", response_model=AuthPingOut)
def auth_ping():
    """Probe que usa el frontend para saber si hay una sesión de Cloudflare Access
    válida: si esta request llegó acá es que sí la hay (o el chequeo liviano del
    header pasó) — no hace falta lógica extra, solo responder."""
    return AuthPingOut()


@router.get("/login", response_class=HTMLResponse)
def login_redirect():
    """El botón "Iniciar sesión" del frontend navega el navegador (no un fetch) hasta
    acá, porque Cloudflare Access solo puede mostrar su pantalla de login en una
    navegación real de página — un fetch() en segundo plano nunca la dispara (el
    redirect cross-origin al login de Cloudflare rompe por CORS antes de mostrarse).
    Al volver de un login exitoso, esta ruta ya no muestra el JSON de auth/ping:
    redirige de una a la PWA, que para entonces ya tiene la cookie de sesión."""
    return "<meta http-equiv=\"refresh\" content=\"0; url=/\">Redirigiendo…"


@router.get("/wallet", response_model=WalletOut)
def get_wallet():
    return WalletOut(wallet_balance=get_current_wallet_balance())


@router.get("/items/{type_id}/recommendation", response_model=OpportunityOut | None)
def get_item_recommendation(type_id: int):
    """Recalcula la recomendación de sizing al vuelo contra el wallet en vivo (no
    depende de un snapshot de hasta 4h de antigüedad del motor de mercado) — movido
    tal cual desde el antiguo bloque live_recommendation de get_item_detail()."""
    conn = _db()
    try:
        status_row = conn.execute(
            f"SELECT {ITEM_SELECT_COLS} {ITEM_JOIN} WHERE s.type_id = ?",
            (type_id,),
        ).fetchone()
        if status_row is None:
            raise HTTPException(404, "Ítem no encontrado o sin clasificar todavía")

        snapshot_row = conn.execute(
            "SELECT best_buy, best_sell FROM market_snapshot WHERE type_id = ? "
            "ORDER BY captured_at DESC LIMIT 1",
            (type_id,),
        ).fetchone()

        if snapshot_row is None or not snapshot_row["best_buy"] or not snapshot_row["best_sell"]:
            return None

        settings = get_app_settings_dict(conn)
        eve_config = config_from_settings(EveCalculatorConfig, settings)
        wallet_balance = get_current_wallet_balance()
        volumen_deseado = resolve_volumen_deseado(
            snapshot_row["best_buy"], wallet_balance,
            settings["position_size_pct_wallet"], settings["volumen_deseado_fallback"],
        )
        result = evaluar_oportunidad(
            item=status_row["name"],
            buy=snapshot_row["best_buy"],
            sell=snapshot_row["best_sell"],
            volumen_deseado=volumen_deseado,
            volumen_diario_real=status_row["volumen_diario_real"],
            config=eve_config,
        )
        return OpportunityOut(
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            buy=result.buy,
            sell=result.sell,
            volumen_deseado=result.volumen_deseado,
            volumen_diario_real=result.volumen_diario_real,
            beneficio=result.beneficio,
            spread_bruto=result.spread_bruto,
            precio_min_venta=result.precio_min_venta,
            roi=result.roi,
            evaluacion_spread=result.evaluacion_spread,
            posicion_vs_volumen=result.posicion_vs_volumen,
            liquidez=result.liquidez,
            recomendacion=result.recomendacion,
            unidades_sugeridas=result.unidades_sugeridas,
        )
    finally:
        conn.close()


@router.get("/character-orders", response_model=list[CharacterOrderOut])
def list_character_orders(undercut_only: bool = False):
    """Tus órdenes activas, con la posición calculada por el motor de posiciones
    (scheduler/orders_run.py) contra el libro de órdenes real de cada ítem: cuántas
    órdenes te compiten por delante (orders_ahead) y por cuánto (price_gap vs
    best_price). Funciona para cualquier región, no solo The Forge."""
    conn = _db()
    try:
        query = (
            "SELECT co.order_id, co.type_id, it.name, co.is_buy_order, co.price, "
            "co.volume_remain, co.volume_total, co.is_undercut, co.region_id, "
            "co.orders_ahead, co.price_gap, co.best_price, "
            "co.first_seen_at, co.last_seen_at "
            "FROM character_order co "
            "JOIN item_type it ON it.type_id = co.type_id"
        )
        if undercut_only:
            query += " WHERE co.is_undercut = 1"
        query += " ORDER BY co.is_undercut DESC, co.last_seen_at DESC"

        rows = conn.execute(query).fetchall()
        return [CharacterOrderOut(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.get("/character-orders/closed", response_model=list[CharacterOrderClosedOut])
def list_character_orders_closed(limit: int = 50):
    _check_limit(limit)
    """R4: órdenes tuyas completadas/expiradas/canceladas recientemente."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT co.order_id, co.type_id, it.name, co.is_buy_order, co.price, "
            "co.final_state, co.closed_at "
            "FROM character_order_closed co "
            "JOIN item_type it ON it.type_id = co.type_id "
            "ORDER BY co.closed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [CharacterOrderClosedOut(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.get("/character-orders/fills", response_model=list[CharacterOrderFillOut])
def list_character_order_fills(limit: int = 50):
    _check_limit(limit)
    """Historial de ejecuciones parciales de tus órdenes activas: el motor de
    posiciones (scheduler/orders_run.py, cada 5 min) persiste una fila acá cada vez
    que detecta que volume_remain bajó sin que la orden se cerrara del todo."""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT cf.id, cf.order_id, cf.type_id, it.name, cf.is_buy_order, cf.price, "
            "cf.filled_units, cf.volume_remain, cf.filled_at "
            "FROM character_order_fill cf "
            "JOIN item_type it ON it.type_id = cf.type_id "
            "ORDER BY cf.filled_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [CharacterOrderFillOut(**dict(r)) for r in rows]
    finally:
        conn.close()


@router.post("/character-orders/refresh", response_model=list[CharacterOrderOut])
def refresh_character_orders():
    """Dispara un re-fetch en vivo de tus órdenes contra la ESI (no espera al motor
    de posiciones): reusa la misma lógica que corre cada 5 min
    (scheduler/orders_run.py), y devuelve la lista de órdenes activas ya actualizada.
    notify=False: este refresco es manual (el usuario está mirando la pantalla), así
    que no tiene sentido mandarle además un Telegram — el motor de 5 min ya se encarga
    de avisar cuando el usuario NO está mirando."""
    session = get_valid_session()
    if session is None:
        raise HTTPException(
            409, "Sin sesión ESI autorizada. Corré 'python scripts/authorize.py' primero.",
        )

    base_url = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL)
    user_agent = os.environ.get("ESI_USER_AGENT", "eve-market-screener")
    db_path = os.environ.get("DB_PATH", "./storage/market.db")

    try:
        with EsiClient(base_url=base_url, user_agent=user_agent) as client:
            check_character_orders(client, db_path, notify=False)
    except Exception as exc:
        logger.exception("Falló el refresco de órdenes contra la ESI")
        raise HTTPException(502, "La ESI rechazó el refresco de órdenes.") from exc

    return list_character_orders()


@router.post("/items/{type_id}/open-in-client", response_model=OpenWindowOut)
def open_in_client(type_id: int):
    """R4 del backlog: abre la ventana de mercado del ítem en tu cliente de EVE
    (tenés que estar logueado con el mismo personaje que autorizó la app)."""
    session = get_valid_session()
    if session is None:
        raise HTTPException(
            409, "Sin sesión ESI autorizada. Corré 'python scripts/authorize.py' primero.",
        )
    access_token, _character_id = session

    base_url = os.environ.get("ESI_BASE_URL", DEFAULT_BASE_URL)
    user_agent = os.environ.get("ESI_USER_AGENT", "eve-market-screener")
    try:
        with EsiClient(base_url=base_url, user_agent=user_agent) as client:
            client.open_market_window(type_id, access_token)
    except Exception as exc:
        logger.exception("Falló la apertura de ventana en el cliente de EVE")
        raise HTTPException(502, "La ESI rechazó la apertura de ventana.") from exc

    return OpenWindowOut(opened=True, detail="Ventana abierta en el cliente de EVE.")


@router.get("/settings", response_model=list[AppSettingOut])
def list_app_settings():
    """Todos los parámetros configurables del programa (pantalla Ajustes de la PWA),
    categorizados. Agregar uno nuevo es agregar una entrada en
    storage/settings_registry.py — este endpoint no necesita tocarse. Los motores los
    leen de acá en cada corrida, así que un cambio tarda hasta la próxima corrida en
    reflejarse (cada 4h para el motor de mercado, cada 5 min para el de posiciones)."""
    conn = _db()
    try:
        return [AppSettingOut(**dict(r)) for r in get_app_settings(conn)]
    finally:
        conn.close()


@router.put("/settings/{key}", response_model=AppSettingOut)
def update_app_setting_route(key: str, body: AppSettingUpdateIn):
    setting_def = SETTINGS_BY_KEY.get(key)
    if setting_def is None:
        raise HTTPException(404, f"No existe el parámetro '{key}'")
    if not math.isfinite(body.value) or body.value > 1e12:
        raise HTTPException(422, "El valor debe ser un número finito")
    if body.value < 0:
        raise HTTPException(422, "El valor no puede ser negativo")
    if key in STRICTLY_POSITIVE_KEYS and body.value <= 0:
        raise HTTPException(422, f"'{setting_def.label}' es indispensable: no puede ser 0 ni negativo")

    conn = _db()
    try:
        update_app_setting(conn, key, body.value)
        row = next(r for r in get_app_settings(conn) if r["key"] == key)
        return AppSettingOut(**dict(row))
    finally:
        conn.close()


@router.post("/settings/reset", response_model=list[AppSettingOut])
def reset_app_settings_route():
    """Botón "Restablecer valores por defecto" de Ajustes: resetea TODOS los
    parámetros a su default_value (storage/settings_registry.py)."""
    conn = _db()
    try:
        reset_app_settings(conn)
        return [AppSettingOut(**dict(r)) for r in get_app_settings(conn)]
    finally:
        conn.close()
