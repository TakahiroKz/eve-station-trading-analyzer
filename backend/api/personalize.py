"""Screener personalizado (fase 5 de EF-02): ROI, estado y puntaje con las comisiones del jugador.

El Screener guarda por ítem el ROI, la evaluación del spread y el estado calculados con las comisiones por defecto (los
factores 0,901 / 1,024 de Ajustes). Con ``profile=mine`` y una sesión se recalculan al vuelo con los factores del perfil
del jugador en el mercado pedido, con el mismo código del motor:

* ROI: ``venta·fv / (compra·fc) − 1`` con los factores del jugador.
* Bandas de spread: están definidas en spread bruto para las comisiones de referencia; equivalen a bandas de ROI neto, así
  que se trasladan a los factores del jugador (el mismo ROI neto de siempre marca los mismos tramos). Con el perfil por
  defecto no cambia nada.
* El estado (POTENCIAL, EN_OBSERVACION, …) se vuelve a clasificar con esas bandas; la liquidez y los mínimos de volumen y de
  operaciones son los guardados. Un precio incoherente sigue descartado.

Todo lo demás (puntaje, elegibilidad, recomendación, unidades) usa los ajustes con los factores y bandas sustituidos.
"""
from dataclasses import dataclass

from fastapi import HTTPException, Request

from analytics.classification import classify
from analytics.eve_calculator import EveCalculatorConfig, config_from_settings, evaluar_spread
from analytics.opportunity import parse_inputs_blob
from backend.api.auth import NO_STORE, _config, _current_user
from finance.hubs import HUB_BY_MARKET
from finance.user_profile import build_profile, fee_summary, screener_factors
from storage import users_db

SPREAD_KEYS = ("spread_perdida_max", "spread_casi_cero_max", "spread_pequeno_max", "spread_buen_margen_max",
               "spread_muy_bueno_max")
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


@dataclass(frozen=True)
class ProfileContext:
    market_id: str
    factors: tuple[float, float]    # (sales_tax_factor, buy_fee_factor) del jugador en este mercado
    active: bool                    # False si son los de referencia: no cambia nada
    info: dict                      # lo que se muestra al jugador

    def apply(self, settings: dict) -> dict:
        """Los ajustes (con o sin capital propio) con los factores y bandas del jugador; sin cambios si no está activo."""
        return personal_settings(settings, *self.factors) if self.active else settings


def personal_settings(settings: dict, sales_tax_factor: float, buy_fee_factor: float) -> dict:
    """Los ajustes con los factores del jugador y las bandas de spread trasladadas a ellos (mismo ROI neto)."""
    st0, bf0 = float(settings["sales_tax_factor"]), float(settings["buy_fee_factor"])
    k = (st0 * buy_fee_factor) / (bf0 * sales_tax_factor)       # (1 + banda') = (1 + banda) · k; con k = 1 las bandas quedan igual
    out = dict(settings, sales_tax_factor=sales_tax_factor, buy_fee_factor=buy_fee_factor)
    for key in SPREAD_KEYS:
        out[key] = round((1 + float(settings[key])) * k - 1, 10)
    return out


def personalize_row(row, settings: dict) -> dict:
    """La fila con roi, evaluacion_spread, status y reason recalculados con los ajustes (ya personales)."""
    out = dict(row)
    buy, sell = row["best_buy"], row["best_sell"]
    if not buy or buy <= 0 or sell is None:
        return out
    config = config_from_settings(EveCalculatorConfig, settings)
    out["roi"] = round(sell * config.sales_tax_factor / (buy * config.buy_fee_factor) - 1, 4)
    spread_eval = evaluar_spread(sell / buy - 1, config)
    out["evaluacion_spread"] = spread_eval
    if parse_inputs_blob(row["score_inputs"] if "score_inputs" in row.keys() else None)["sane"]:
        out["status"], out["reason"] = classify(
            spread_eval, row["liquidez"], row["avg_daily_volume_7d"], row["avg_daily_order_count_7d"],
            min_daily_volume_7d=settings["min_daily_volume_7d"], min_daily_order_count_7d=settings["min_daily_order_count_7d"])
    return out


def roi_filter_sql(column_buy: str, column_sell: str, settings: dict, operator: str) -> str:
    """Condición exacta sobre el ROI personal sin recorrer el mercado en Python: venta·fv ≥ compra·fc·(1 + m)."""
    fv, fc = float(settings["sales_tax_factor"]), float(settings["buy_fee_factor"])
    return f"({column_buy} > 0 AND {column_sell} * {fv!r} {operator} {column_buy} * {fc!r} * (1 + ?))"


def load_context(request: Request, market_id: str, base_settings: dict) -> ProfileContext:
    """El contexto del jugador con sesión para ese mercado. 401 sin sesión: ``profile=mine`` nunca cae en silencio al perfil
    por defecto (el jugador creería ver sus números)."""
    if _config() is None:
        raise HTTPException(503, "Las cuentas no están disponibles.", headers=NO_STORE)
    conn = users_db.connect()
    try:
        user = _current_user(conn, request)
        if user is None:
            raise HTTPException(401, "No has iniciado sesión.", headers=NO_STORE)
        row = users_db.get_profile(conn, user["character_id"])
    finally:
        conn.close()
    hub = HUB_BY_MARKET.get(market_id)
    if hub is None:
        raise HTTPException(422, "Este mercado no tiene estación de referencia.", headers=NO_STORE)
    from backend.api.me import _loads          # evita un ciclo de importación
    profile, _skills, _standings = build_profile(
        hub, _loads(row["skills_json"]) if row else None, _loads(row["standings_json"]) if row else None,
        (_loads(row["override_json"]) if row else None) or {})
    st, bf = screener_factors(profile)
    active = (st, bf) != (round(float(base_settings["sales_tax_factor"]), 4), round(float(base_settings["buy_fee_factor"]), 4))
    info = {**fee_summary(profile), "source": profile.source, "market_id": market_id, "station": hub.station_name,
            "personalized": active}
    return ProfileContext(market_id, (st, bf), active, info)
