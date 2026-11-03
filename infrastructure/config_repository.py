"""Carga y persiste la configuracion de la aplicacion (seccion 19, 22, 27, 28, 43 de la HU).

Todos los umbrales, pesos y costes son configurables por el usuario y se guardan en
config/user_config.json, que sobreescribe config/default_config.json.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict

from domain.models import (
    CapitalConfig,
    CostConfig,
    HardStopConfig,
    ScoreWeights,
    ThresholdConfig,
    TraderConfig,
)
from infrastructure.paths import DEFAULT_CONFIG_PATH, USER_CONFIG_PATH, ensure_dirs


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_raw_config() -> Dict[str, Any]:
    ensure_dirs()
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        base = json.load(f)
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            override = json.load(f)
        base = _deep_merge(base, override)
    return base


def save_raw_config(config: Dict[str, Any]) -> None:
    ensure_dirs()
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


class AppConfig:
    """Fachada tipada sobre la configuracion cruda, lista para inyectar en el motor de calculo."""

    def __init__(self, raw: Dict[str, Any]):
        self.raw = raw

    @property
    def thresholds(self) -> ThresholdConfig:
        t = self.raw["thresholds"]
        return ThresholdConfig(
            trend_favorable_min=t["trend"]["favorable_min"],
            trend_neutral_min=t["trend"]["neutral_min"],
            trend_caution_min=t["trend"]["caution_min"],
            volatility_low_max=t["volatility"]["low_max"],
            volatility_medium_max=t["volatility"]["medium_max"],
            spread_insufficient_max=t["spread_pct"]["insufficient_max"],
            spread_low_max=t["spread_pct"]["low_max"],
            spread_good_max=t["spread_pct"]["good_max"],
            spread_very_good_max=t["spread_pct"]["very_good_max"],
            discrepancy_pct_threshold=t["discrepancy_pct_threshold"],
            score_buy_min=t["score_buy_min"],
            score_caution_min=t["score_caution_min"],
            score_watch_min=t["score_watch_min"],
        )

    @property
    def hard_stops(self) -> HardStopConfig:
        h = self.raw["hard_stops"]
        return HardStopConfig(
            trend_min_pct=h["trend_min_pct"],
            volatility_max_pct=h["volatility_max_pct"],
            net_margin_min_pct=h["net_margin_min_pct"],
            liquidity_insufficient_blocks=h["liquidity_insufficient_blocks"],
        )

    @property
    def score_weights(self) -> ScoreWeights:
        w = self.raw["score_weights"]
        return ScoreWeights(
            net_margin=w["net_margin"],
            profit_unit=w["profit_unit"],
            liquidity=w["liquidity"],
            profit_day=w["profit_day"],
            trend=w["trend"],
            volatility=w["volatility"],
            capital_efficiency=w["capital_efficiency"],
            market_depth=w["market_depth"],
        )

    @property
    def costs(self) -> CostConfig:
        c = self.raw["costs"]
        return CostConfig(
            broker_fee_buy_pct=c["broker_fee_buy_pct"],
            broker_fee_sell_pct=c["broker_fee_sell_pct"],
            sales_tax_pct=c["sales_tax_pct"],
            relist_fee_pct=c["relist_fee_pct"],
        )

    @property
    def capital(self) -> CapitalConfig:
        c = self.raw["capital"]
        return CapitalConfig(
            total_isk=c["total_isk"],
            trading_isk=c["trading_isk"],
            reserve_isk=c["reserve_isk"],
            max_pct_per_position=c["max_pct_per_position"],
            max_pct_per_product=c["max_pct_per_product"],
        )

    @property
    def trader(self) -> TraderConfig:
        t = self.raw["trader"]
        return TraderConfig(
            account_type=t["account_type"],
            broker_relations_level=t["broker_relations_level"],
            accounting_level=t["accounting_level"],
            standing=t["standing"],
            station=t["station"],
            capital=self.capital,
        )


def load_config() -> AppConfig:
    return AppConfig(load_raw_config())


def save_config(config: AppConfig) -> None:
    save_raw_config(config.raw)
