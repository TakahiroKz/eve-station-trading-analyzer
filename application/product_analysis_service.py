"""Application layer: orquesta el motor de calculo (domain/*) para producir un AnalysisResult
completo a partir de la entrada del usuario. No contiene formulas propias: solo composicion.
"""
from __future__ import annotations

from domain.breakeven_calculator import calculate_breakeven_sell_price, safety_margin_pct
from domain.capital_efficiency import (
    CapitalEfficiencyResult,
    calculate_capital_efficiency,
    calculate_capital_turnover,
    estimate_profit_per_day,
)
from domain.discrepancy_analyzer import compare_values
from domain.fee_calculator import calculate_fees
from domain.hard_stops import HardStopInputs, evaluate_hard_stops
from domain.margin_calculator import calculate_net_margin_pct
from domain.models import ProductInput
from domain.position_sizer import calculate_position_size
from domain.profit_calculator import calculate_net_profit
from domain.recommendation_engine import ExplainedFactor, build_recommendation
from domain.risk_analyzer import (
    Rating,
    RatingLevel,
    classify_liquidity,
    classify_market_depth,
    classify_spread,
    classify_trend,
    classify_volatility,
    evaluate_position_size,
    rating_to_score,
)
from domain.score_engine import ScoreSubfactors, calculate_viability_score, normalize_linear
from domain.spread_calculator import calculate_spread
from infrastructure.config_repository import AppConfig

from application.analysis_result import AnalysisResult


def analyze_product(product: ProductInput, config: AppConfig) -> AnalysisResult:
    thresholds = config.thresholds
    hard_stop_cfg = config.hard_stops
    costs = config.costs
    capital = config.capital
    weights = config.score_weights

    buy_price = product.my_buy_price
    sell_price = product.my_sell_price

    # --- Motor de calculo determinista ---
    spread = calculate_spread(buy_price, sell_price)
    fees = calculate_fees(buy_price, sell_price, costs)
    profit = calculate_net_profit(buy_price, sell_price, fees)
    net_margin_pct = calculate_net_margin_pct(profit.net_profit_unit, buy_price)
    breakeven_price = calculate_breakeven_sell_price(buy_price, costs)
    safety_pct = safety_margin_pct(sell_price, breakeven_price)

    profit_unit_discrepancy = compare_values(
        product.eve_hub.profit_per_unit, profit.net_profit_unit, thresholds.discrepancy_pct_threshold
    )
    margin_discrepancy = compare_values(
        product.eve_hub.margin_pct, net_margin_pct, thresholds.discrepancy_pct_threshold
    )

    position_size = calculate_position_size(
        buy_price, capital, product.eve_hub.volume_day, requested_units=product.my_quantity
    )
    position_compat = evaluate_position_size(buy_price, capital)

    units = position_size.max_units_by_capital if product.my_quantity is None else product.my_quantity
    if position_size.capital_used > 0:
        capital_eff = calculate_capital_efficiency(position_size.capital_used, profit.net_profit_unit, units)
    else:
        # El precio unitario supera el capital maximo por producto: no hay unidades comprables.
        capital_eff = CapitalEfficiencyResult(capital_used=0.0, estimated_profit=0.0, roi_pct=0.0)
    profit_day = estimate_profit_per_day(profit.net_profit_unit, product.eve_hub.volume_day)
    turnover = calculate_capital_turnover(position_size.capital_used, profit_day)

    units_ahead_sell = product.market.units_ahead_on_sell(sell_price)
    units_ahead_buy = product.market.units_ahead_on_buy(buy_price)

    # --- Clasificaciones cualitativas ---
    trend_rating = classify_trend(product.eve_hub.trend_pct, thresholds)
    volatility_rating = classify_volatility(product.eve_hub.volatility_pct, thresholds)
    spread_rating = classify_spread(spread.spread_pct, thresholds)
    liquidity_rating = classify_liquidity(
        product.eve_hub.volume_day, product.market.buy_depth, product.market.sell_depth
    )
    market_depth_rating = classify_market_depth(units_ahead_sell, product.eve_hub.volume_day)

    # --- Score de viabilidad (subfactores normalizados 0-100) ---
    subfactors = ScoreSubfactors(
        net_margin_score=normalize_linear(net_margin_pct, worst=0.0, best=50.0),
        profit_unit_score=normalize_linear(profit.net_profit_unit, worst=0.0, best=buy_price),
        liquidity_score=rating_to_score(liquidity_rating),
        profit_day_score=normalize_linear(
            profit_day, worst=0.0, best=max(position_size.capital_used, 1.0)
        ),
        trend_score=normalize_linear(
            product.eve_hub.trend_pct, worst=hard_stop_cfg.trend_min_pct, best=30.0
        ),
        volatility_score=normalize_linear(
            product.eve_hub.volatility_pct, worst=hard_stop_cfg.volatility_max_pct, best=0.0
        ),
        capital_efficiency_score=normalize_linear(capital_eff.roi_pct, worst=0.0, best=50.0),
        market_depth_score=rating_to_score(market_depth_rating),
    )
    score = calculate_viability_score(subfactors, weights)

    # --- Hard stops: ninguna condicion critica puede ocultarse tras el score ---
    hard_stop_inputs = HardStopInputs(
        trend_pct=product.eve_hub.trend_pct,
        volatility_pct=product.eve_hub.volatility_pct,
        net_margin_pct=net_margin_pct,
        position_exceeds_capital=not position_compat.compatible,
        liquidity_level=liquidity_rating.level,
    )
    violations = evaluate_hard_stops(hard_stop_inputs, hard_stop_cfg)

    # --- Factores explicables para la recomendacion ---
    factors = [
        ExplainedFactor("margen_neto", _rating_from_score(net_margin_pct), f"Margen neto {'atractivo' if net_margin_pct >= 20 else 'ajustado'} ({net_margin_pct:.1f}%)"),
        ExplainedFactor("tendencia", trend_rating, f"Tendencia {trend_rating.label.lower()} ({product.eve_hub.trend_pct:+.1f}%)"),
        ExplainedFactor("volatilidad", volatility_rating, f"Volatilidad {volatility_rating.label.lower()} ({product.eve_hub.volatility_pct:.1f}%)"),
        ExplainedFactor("liquidez", liquidity_rating, f"Liquidez {liquidity_rating.label.lower()} (volumen diario {product.eve_hub.volume_day:.0f})"),
        ExplainedFactor("profundidad", market_depth_rating, f"Profundidad de mercado {market_depth_rating.label.lower()}"),
        ExplainedFactor("spread", spread_rating, f"Spread {spread_rating.label.lower()} ({spread.spread_pct:.1f}%)"),
    ]
    if not position_compat.compatible:
        factors.append(ExplainedFactor(
            "posicion",
            Rating(RatingLevel.BAD, "Incompatible", "🔴"),
            f"Precio unitario ({buy_price:,.0f} ISK) supera el limite de exposicion por producto "
            f"({position_compat.max_capital_per_product:,.0f} ISK) para el capital configurado.",
        ))

    cancel_condition = (
        f"Si el margen neto cae por debajo de {hard_stop_cfg.net_margin_min_pct:.0f}% "
        f"o la tendencia pasa a menos de {hard_stop_cfg.trend_min_pct:.0f}%, reevaluar la posicion."
    )

    recommendation = build_recommendation(score, violations, factors, thresholds, cancel_condition)

    return AnalysisResult(
        item=product.item,
        buy_price=buy_price,
        sell_price=sell_price,
        eve_hub_profit_unit=product.eve_hub.profit_per_unit,
        eve_hub_margin_pct=product.eve_hub.margin_pct,
        volume_day=product.eve_hub.volume_day,
        trend_pct=product.eve_hub.trend_pct,
        volatility_pct=product.eve_hub.volatility_pct,
        eve_hub_profit_day=product.eve_hub.profit_day,
        buy_depth=product.market.buy_depth,
        sell_depth=product.market.sell_depth,
        units_ahead_sell=units_ahead_sell,
        units_ahead_buy=units_ahead_buy,
        spread=spread,
        fees=fees,
        profit=profit,
        net_margin_pct=net_margin_pct,
        breakeven_price=breakeven_price,
        safety_margin_pct=safety_pct,
        profit_unit_discrepancy=profit_unit_discrepancy,
        margin_discrepancy=margin_discrepancy,
        position_size=position_size,
        position_compatibility=position_compat,
        capital_efficiency=capital_eff,
        estimated_profit_per_day=profit_day,
        capital_turnover=turnover,
        trend_rating=trend_rating,
        volatility_rating=volatility_rating,
        spread_rating=spread_rating,
        liquidity_rating=liquidity_rating,
        market_depth_rating=market_depth_rating,
        score=score,
        hard_stop_violations=violations,
        recommendation=recommendation,
    )


def _rating_from_score(net_margin_pct: float) -> Rating:
    if net_margin_pct >= 20:
        return Rating(RatingLevel.EXCELLENT, "Atractivo", "🟢")
    if net_margin_pct >= 5:
        return Rating(RatingLevel.CAUTION, "Ajustado", "🟡")
    return Rating(RatingLevel.BAD, "Insuficiente", "🔴")
