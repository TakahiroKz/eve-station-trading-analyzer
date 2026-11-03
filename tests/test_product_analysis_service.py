from datetime import datetime

from application.product_analysis_service import analyze_product
from domain.models import (
    CapitalConfig,
    CostConfig,
    EveHubSnapshot,
    HardStopConfig,
    MarketOrderLevel,
    MarketSnapshot,
    ProductInput,
    ScoreWeights,
    ThresholdConfig,
    TraderConfig,
)
from infrastructure.config_repository import AppConfig
from infrastructure.paths import DEFAULT_CONFIG_PATH
import json


def load_default_app_config() -> AppConfig:
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        return AppConfig(json.load(f))


def make_gamma_l_input() -> ProductInput:
    eve_hub = EveHubSnapshot(
        item="Imperial Navy Gamma L",
        buy=698_000, sell=997_900, vwap=836_000,
        profit_per_unit=179_400, margin_pct=25.1,
        volume_day=390, trend_pct=26.2, volatility_pct=19.0,
        profit_day=13_980_000, captured_at=datetime(2026, 9, 8, 9, 0),
    )
    market = MarketSnapshot(
        buy_orders=[
            MarketOrderLevel(1, 698_000, 3),
            MarketOrderLevel(2, 697_999, 100),
        ],
        sell_orders=[
            MarketOrderLevel(1, 997_900, 10),
            MarketOrderLevel(2, 998_000, 50),
            MarketOrderLevel(3, 999_000, 100),
        ],
    )
    return ProductInput(
        item="Imperial Navy Gamma L",
        eve_hub=eve_hub,
        market=market,
        my_buy_price=698_000,
        my_sell_price=997_900,
    )


def test_analyze_gamma_l_end_to_end():
    config = load_default_app_config()
    product = make_gamma_l_input()
    result = analyze_product(product, config)

    assert result.spread.spread_isk == 299_900
    assert round(result.spread.spread_pct, 2) == 42.97
    assert result.position_size.max_units_by_capital == 7
    assert round(result.position_size.position_vs_volume_pct, 2) > 0
    assert result.net_margin_pct < result.spread.spread_pct  # los costes reducen el margen
    assert result.recommendation.status is not None
    assert isinstance(result.recommendation.reasons, list)
    assert result.breakeven_price > result.buy_price


def test_analyze_expensive_product_triggers_position_hard_stop():
    config = load_default_app_config()
    eve_hub = EveHubSnapshot(
        item="Unstable Strip Miner Mutaplasmid",
        buy=7_460_000, sell=9_000_000, vwap=8_000_000,
        profit_per_unit=1_000_000, margin_pct=13.4,
        volume_day=50, trend_pct=5.0, volatility_pct=10.0,
        profit_day=1_000_000,
    )
    market = MarketSnapshot(
        buy_orders=[MarketOrderLevel(1, 7_460_000, 1)],
        sell_orders=[MarketOrderLevel(1, 9_000_000, 1)],
    )
    product = ProductInput(
        item="Unstable Strip Miner Mutaplasmid",
        eve_hub=eve_hub, market=market,
        my_buy_price=7_460_000, my_sell_price=9_000_000,
    )
    result = analyze_product(product, config)
    assert result.position_compatibility.compatible is False
    assert any(v.code == "POSITION_EXCEEDS_CAPITAL" for v in result.hard_stop_violations)
    assert result.recommendation.status.value == "DO_NOT_BUY"
