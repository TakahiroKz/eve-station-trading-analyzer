"""Entidades del dominio. Sin logica de calculo aqui: solo estructuras de datos."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class MarketOrderLevel:
    """Un nivel de orden de compra o venta observado en EVE Online."""
    position: int
    price: float
    quantity: int


@dataclass
class EveHubSnapshot:
    """Datos externos observados en EVE-Hub. NUNCA se recalculan: se almacenan tal cual."""
    item: str
    buy: float
    sell: float
    vwap: float
    profit_per_unit: float
    margin_pct: float
    volume_day: float
    trend_pct: float
    volatility_pct: float
    profit_day: float
    captured_at: datetime = field(default_factory=datetime.now)


@dataclass
class MarketSnapshot:
    """Ordenes de compra/venta observadas directamente en el mercado de EVE Online."""
    buy_orders: List[MarketOrderLevel] = field(default_factory=list)
    sell_orders: List[MarketOrderLevel] = field(default_factory=list)

    @property
    def buy_depth(self) -> int:
        return sum(o.quantity for o in self.buy_orders)

    @property
    def sell_depth(self) -> int:
        return sum(o.quantity for o in self.sell_orders)

    @property
    def best_buy(self) -> Optional[float]:
        return max((o.price for o in self.buy_orders), default=None)

    @property
    def best_sell(self) -> Optional[float]:
        return min((o.price for o in self.sell_orders), default=None)

    def units_ahead_on_sell(self, my_sell_price: float) -> int:
        """Unidades en venta con precio igual o mejor (mas barato) que el mio."""
        return sum(o.quantity for o in self.sell_orders if o.price <= my_sell_price)

    def units_ahead_on_buy(self, my_buy_price: float) -> int:
        """Unidades en compra con precio igual o mejor (mas caro) que el mio."""
        return sum(o.quantity for o in self.buy_orders if o.price >= my_buy_price)


@dataclass
class CostConfig:
    broker_fee_buy_pct: float
    broker_fee_sell_pct: float
    sales_tax_pct: float
    relist_fee_pct: float


@dataclass
class CapitalConfig:
    total_isk: float
    trading_isk: float
    reserve_isk: float
    max_pct_per_position: float
    max_pct_per_product: float


@dataclass
class TraderConfig:
    account_type: str  # "Alpha" | "Omega"
    broker_relations_level: int
    accounting_level: int
    standing: float
    station: str
    capital: CapitalConfig


@dataclass
class ThresholdConfig:
    trend_favorable_min: float
    trend_neutral_min: float
    trend_caution_min: float
    volatility_low_max: float
    volatility_medium_max: float
    spread_insufficient_max: float
    spread_low_max: float
    spread_good_max: float
    spread_very_good_max: float
    discrepancy_pct_threshold: float
    score_buy_min: float
    score_caution_min: float
    score_watch_min: float


@dataclass
class HardStopConfig:
    trend_min_pct: float
    volatility_max_pct: float
    net_margin_min_pct: float
    liquidity_insufficient_blocks: bool


@dataclass
class ScoreWeights:
    net_margin: float
    profit_unit: float
    liquidity: float
    profit_day: float
    trend: float
    volatility: float
    capital_efficiency: float
    market_depth: float


@dataclass
class ProductInput:
    """Entrada completa registrada por el usuario para un producto."""
    item: str
    eve_hub: EveHubSnapshot
    market: MarketSnapshot
    my_buy_price: float
    my_sell_price: float
    my_quantity: Optional[int] = None  # si None, se calcula la cantidad maxima recomendada
