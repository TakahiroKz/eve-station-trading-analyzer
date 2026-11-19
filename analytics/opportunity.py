"""Elegibilidad, recomendación y explicación de una oportunidad (EF-01.06 y EF-01.08 adaptados).

Reglas de negocio deterministas sobre el puntaje de analytics.scoring: primero los filtros duros
(un puntaje alto nunca los salta), luego la elegibilidad (NO_ELIGIBLE / ELIGIBLE / RECOMMENDED) y la
acción del motor (BUY_CANDIDATE / WAIT / REJECT). Cada resultado lleva códigos de justificación y
"qué tendría que cambiar". Son evaluaciones del motor, no órdenes: HOLD y SELL_CANDIDATE necesitan las
posiciones del usuario y quedan fuera de esta fase.

Los parámetros viven en Ajustes (storage/settings_registry.py); los mínimos de volumen y de operaciones
son los mismos de analytics.classification para no tener dos criterios distintos.
"""
import json
from dataclasses import dataclass

from analytics.eve_calculator import EveCalculatorConfig, beneficio_unitario, config_from_settings
from analytics.scoring import (
    ScoreConfig,
    ScoreInputs,
    ScoreResult,
    holding_days,
    reference_position,
    score_opportunity,
)


# Códigos que viajan en la evaluación (frontend/app/src/i18n: score.code.*); ver NOTE_CODES en scoring.py.
FILTER_CODES = (
    "CLASSIFIED_DISCARDED", "PRICE_INCONSISTENT", "NO_VALID_ORDERS", "NET_PROFIT_NOT_POSITIVE",
    "STALE_MARKET_DATA", "VOLUME_BELOW_MINIMUM", "NET_PROFIT_BELOW_MINIMUM", "HIGH_VOLATILITY",
)
REASON_CODES = (
    "SCORE_ABOVE_MINIMUM", "ROI_ABOVE_MINIMUM", "LIQUIDITY_ABOVE_MINIMUM", "HOLDING_TIME_OK",
    "SCORE_BELOW_MINIMUM", "ROI_BELOW_MINIMUM", "LOW_LIQUIDITY", "EXCESSIVE_HOLDING_TIME",
)


@dataclass
class OpportunityConfig:
    """Los nombres de campo son claves de app_settings."""
    min_net_roi: float = 0.05              # ROI neto mínimo para recomendar (fracción)
    min_net_profit: float = 100_000.0      # beneficio neto mínimo (ISK) de la posición de referencia
    min_liquidity_score: float = 60.0
    max_risk_score: float = 60.0           # riesgo = 100 - puntuación de estabilidad
    max_holding_days: float = 7.0
    max_market_data_age_min: float = 30.0
    min_opportunity_score: float = 65.0
    min_daily_volume_7d: float = 10.0      # el mismo mínimo de classify()


@dataclass
class OpportunityContext:
    unit_profit: float            # beneficio neto por unidad (eve_calculator.beneficio_unitario)
    price_sane: bool              # best_buy/best_sell coherentes con el histórico (analytics.sanity)
    data_age_min: float | None    # antigüedad del snapshot de órdenes, en minutos


def _factor(score: ScoreResult, key: str):
    return next((f for f in score.factors if f.key == key), None)


def assess_opportunity(inputs: ScoreInputs, context: OpportunityContext, score: ScoreResult,
                       score_config: ScoreConfig | None = None,
                       config: OpportunityConfig | None = None) -> dict:
    """Devuelve {eligibility, recommendation, reference}. Todo en tipos JSON para guardarlo tal cual."""
    score_config = score_config or ScoreConfig()
    config = config or OpportunityConfig()

    ref = reference_position(score_config, inputs.best_buy)
    days = holding_days(ref["quantity"], inputs.volume_7d, score_config)
    net_profit = context.unit_profit * ref["quantity"]
    stability = _factor(score, "stability")
    liquidity = _factor(score, "liquidity")
    risk = None if stability is None else 100.0 - stability.score
    stale = context.data_age_min is not None and context.data_age_min > config.max_market_data_age_min

    # --- Filtros duros: cualquiera incumplido => NO_ELIGIBLE, sin importar el puntaje ---
    failed: list[str] = []
    passed: list[str] = []

    def check(code: str, ok: bool) -> None:
        (passed if ok else failed).append(code)

    check("NOT_CLASSIFIED_DISCARDED", inputs.status != "DESCARTADO")
    check("PRICE_CONSISTENT", context.price_sane)
    check("VALID_ORDERS", inputs.best_buy > 0 and inputs.buy_orders > 0 and inputs.sell_orders > 0)
    check("NET_PROFIT_POSITIVE", context.unit_profit > 0)
    check("DATA_FRESH", not stale)
    if config.min_daily_volume_7d > 0:
        check("MINIMUM_VOLUME", inputs.volume_7d >= config.min_daily_volume_7d)
    check("MINIMUM_PROFIT", net_profit >= config.min_net_profit)
    if risk is not None:
        check("RISK_WITHIN_LIMIT", risk <= config.max_risk_score)

    hard_ok = not failed

    # --- Criterios de recomendación (solo cuentan si pasó los filtros duros) ---
    reasons: list[str] = []
    to_change: list[dict] = []

    def condition(code_ok: str, code_bad: str, ok: bool, current, needed) -> None:
        if ok:
            reasons.append(code_ok)
        else:
            reasons.append(code_bad)
            to_change.append({"code": code_bad, "current": current, "needed": needed})

    total = score.total if score.total is not None else 0.0
    condition("SCORE_ABOVE_MINIMUM", "SCORE_BELOW_MINIMUM", total >= config.min_opportunity_score,
              round(total, 1), config.min_opportunity_score)
    condition("ROI_ABOVE_MINIMUM", "ROI_BELOW_MINIMUM", inputs.roi >= config.min_net_roi,
              round(inputs.roi, 4), config.min_net_roi)
    condition("LIQUIDITY_ABOVE_MINIMUM", "LOW_LIQUIDITY",
              liquidity is not None and liquidity.score >= config.min_liquidity_score,
              None if liquidity is None else round(liquidity.score, 1), config.min_liquidity_score)
    condition("HOLDING_TIME_OK", "EXCESSIVE_HOLDING_TIME", days is not None and days <= config.max_holding_days,
              None if days is None else round(days, 2), config.max_holding_days)

    if stale:
        # Como en EF-01.08: con datos desactualizados primero se espera una actualización.
        eligibility, action = "NO_ELIGIBLE", "WAIT"
    elif not hard_ok:
        eligibility, action = "NO_ELIGIBLE", "REJECT"
    elif all(code in {"SCORE_ABOVE_MINIMUM", "ROI_ABOVE_MINIMUM", "LIQUIDITY_ABOVE_MINIMUM", "HOLDING_TIME_OK"}
             for code in reasons):
        eligibility, action = "RECOMMENDED", "BUY_CANDIDATE"
    else:
        eligibility, action = "ELIGIBLE", "WAIT"

    failure_codes = {
        "NOT_CLASSIFIED_DISCARDED": "CLASSIFIED_DISCARDED", "PRICE_CONSISTENT": "PRICE_INCONSISTENT",
        "VALID_ORDERS": "NO_VALID_ORDERS", "NET_PROFIT_POSITIVE": "NET_PROFIT_NOT_POSITIVE",
        "DATA_FRESH": "STALE_MARKET_DATA", "MINIMUM_VOLUME": "VOLUME_BELOW_MINIMUM",
        "MINIMUM_PROFIT": "NET_PROFIT_BELOW_MINIMUM", "RISK_WITHIN_LIMIT": "HIGH_VOLATILITY",
    }
    failed_codes = [failure_codes[c] for c in failed]
    if not hard_ok:
        # Qué tendría que cambiar para superar el filtro más relevante.
        for code in failed:
            current, needed = {
                "NET_PROFIT_POSITIVE": (round(context.unit_profit, 2), "> 0"),
                "DATA_FRESH": (None if context.data_age_min is None else round(context.data_age_min, 1),
                               config.max_market_data_age_min),
                "MINIMUM_VOLUME": (round(inputs.volume_7d, 1), config.min_daily_volume_7d),
                "MINIMUM_PROFIT": (round(net_profit), config.min_net_profit),
                "RISK_WITHIN_LIMIT": (None if risk is None else round(risk, 1), config.max_risk_score),
            }.get(code, (None, None))
            to_change.insert(0, {"code": failure_codes[code], "current": current, "needed": needed})

    return {
        "eligibility": {"status": eligibility, "failed_filters": failed_codes, "passed_filters": passed},
        "recommendation": {"action": action, "reason_codes": reasons if hard_ok else failed_codes + reasons,
                           "to_change": to_change if action != "BUY_CANDIDATE" else []},
        "reference": {**ref, "holding_days": None if days is None else round(days, 2),
                      "net_profit": round(net_profit)},
    }


def inputs_blob(price_cv: float | None, data_age_min: float | None, price_sane: bool) -> str:
    """Lo que el puntaje necesita y no está ya en la fila de item_status (se guarda en score_inputs)."""
    return json.dumps({"cv": None if price_cv is None else round(price_cv, 4),
                       "age": None if data_age_min is None else round(data_age_min, 1),
                       "sane": bool(price_sane)}, separators=(",", ":"))


def parse_inputs_blob(blob: str | None) -> dict:
    try:
        data = json.loads(blob) if blob else {}
    except ValueError:
        data = {}
    return {"cv": data.get("cv"), "age": data.get("age"), "sane": data.get("sane", True)}


def evaluate_item(inputs: ScoreInputs, best_sell: float, extras: dict, settings: dict) -> tuple[ScoreResult, dict]:
    """Único punto de cálculo del puntaje y la evaluación: lo llaman el ciclo de mercado (que guarda el
    resultado) y la API del detalle (que recalcula la explicación completa). `extras` = parse_inputs_blob."""
    score_config = config_from_settings(ScoreConfig, settings)
    opportunity_config = config_from_settings(OpportunityConfig, settings)
    eve_config = config_from_settings(EveCalculatorConfig, settings)
    score = score_opportunity(inputs, score_config)
    context = OpportunityContext(
        unit_profit=beneficio_unitario(inputs.best_buy, best_sell, eve_config),
        price_sane=bool(extras.get("sane", True)),
        data_age_min=extras.get("age"),
    )
    return score, assess_opportunity(inputs, context, score, score_config, opportunity_config)
