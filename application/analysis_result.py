"""Estructura agregada con el resultado completo de analizar un producto."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from domain.breakeven_calculator import safety_margin_pct
from domain.capital_efficiency import CapitalEfficiencyResult, CapitalTurnoverResult
from domain.discrepancy_analyzer import DiscrepancyResult
from domain.fee_calculator import FeeBreakdown
from domain.hard_stops import HardStopViolation
from domain.position_sizer import PositionSizeResult
from domain.profit_calculator import ProfitResult
from domain.recommendation_engine import RecommendationResult
from domain.risk_analyzer import PositionCompatibility, Rating
from domain.score_engine import ScoreResult
from domain.spread_calculator import SpreadResult


@dataclass
class AnalysisResult:
    item: str
    buy_price: float
    sell_price: float

    # EVE-Hub (observado, nunca recalculado)
    eve_hub_profit_unit: float
    eve_hub_margin_pct: float
    volume_day: float
    trend_pct: float
    volatility_pct: float
    eve_hub_profit_day: float

    # Mercado
    buy_depth: int
    sell_depth: int
    units_ahead_sell: int
    units_ahead_buy: int

    # Motor de calculo
    spread: SpreadResult
    fees: FeeBreakdown
    profit: ProfitResult
    net_margin_pct: float
    breakeven_price: float
    safety_margin_pct: float

    profit_unit_discrepancy: DiscrepancyResult
    margin_discrepancy: DiscrepancyResult

    position_size: PositionSizeResult
    position_compatibility: PositionCompatibility
    capital_efficiency: CapitalEfficiencyResult
    estimated_profit_per_day: float
    capital_turnover: CapitalTurnoverResult

    trend_rating: Rating
    volatility_rating: Rating
    spread_rating: Rating
    liquidity_rating: Rating
    market_depth_rating: Rating

    score: ScoreResult
    hard_stop_violations: List[HardStopViolation]
    recommendation: RecommendationResult

    def to_summary_dict(self) -> Dict[str, Any]:
        """Version aplanada para persistir en historial (infrastructure/analysis_repository.py)."""
        return {
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "eve_hub_profit_unit": self.eve_hub_profit_unit,
            "eve_hub_margin_pct": self.eve_hub_margin_pct,
            "volume_day": self.volume_day,
            "trend_pct": self.trend_pct,
            "volatility_pct": self.volatility_pct,
            "eve_hub_profit_day": self.eve_hub_profit_day,
            "calc_net_profit_unit": self.profit.net_profit_unit,
            "calc_net_margin_pct": self.net_margin_pct,
            "calc_roi_pct": self.capital_efficiency.roi_pct,
            "recommended_units": self.position_size.max_units_by_capital,
            "capital_used": self.position_size.capital_used,
            "score": self.score.total_score,
            "recommendation_status": self.recommendation.status.value,
            "recommendation_label": self.recommendation.label,
            "breakeven_price": self.breakeven_price,
            "reasons": self.recommendation.reasons,
            "risks": self.recommendation.risks,
            "hard_stop_messages": self.recommendation.hard_stop_messages,
        }
