"""Contrato FinancialAssessment y orquestación del motor (EF-02)."""
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from finance import book, capital, targets
from finance.fees import Profile, Venue, broker_fee_rate, dec, relist_discount, sales_tax_rate
from finance.profit import Relist, compute_trade
from finance.rules import CENT, DEFAULT_RULES, ENGINE_VERSION, RULE_STATUS, RULES_VERSION, RuleSet

RATIO = Decimal("0.000001")
MODES = ("LIMIT", "IMMEDIATE")


@dataclass(frozen=True)
class TradeInput:
    units: object
    buy_mode: str = "LIMIT"
    buy_price: object = None
    asks: tuple = ()
    sell_mode: str = "LIMIT"
    sell_price: object = None
    bids: tuple = ()
    profile: Profile = field(default_factory=Profile)
    venue: Venue = field(default_factory=Venue)
    relists: tuple = ()                 # tuplas (side, old_price, new_price)
    target_roi: object = 0
    available_capital: object = None
    rules: RuleSet = DEFAULT_RULES


@dataclass
class FinancialAssessment:
    calculation_status: str                       # VALID | INCOMPLETE
    engine_version: str = ENGINE_VERSION
    rules_version: str = RULES_VERSION
    warnings: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)  # foto de lo usado: reproducible
    rates: dict = field(default_factory=dict)
    result: dict | None = None
    targets: dict = field(default_factory=dict)
    capital: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        def conv(v):
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            return v
        return conv(dict(self.__dict__))


def _money(x: Decimal | None):
    return None if x is None else x.quantize(CENT, rounding=ROUND_HALF_UP)


def _ratio(x: Decimal | None):
    return None if x is None else x.quantize(RATIO, rounding=ROUND_HALF_UP)


def _flag_unverified(out: FinancialAssessment, used: set[str]) -> None:
    out.warnings.extend(f"UNVERIFIED_RULE:{r}" for r in sorted(used) if RULE_STATUS[r] != "CONFIRMADA")


def _incomplete(out: FinancialAssessment, warning: str, used: set[str]) -> FinancialAssessment:
    out.calculation_status = "INCOMPLETE"
    out.warnings.append(warning)
    _flag_unverified(out, used)
    return out


def evaluate(inp: TradeInput) -> FinancialAssessment:
    rules, profile, venue = inp.rules, inp.profile, inp.venue
    profile.validate(rules)
    if inp.buy_mode not in MODES or inp.sell_mode not in MODES:
        raise ValueError("buy_mode y sell_mode deben ser LIMIT o IMMEDIATE")
    units = dec(inp.units)
    if units <= 0 or units != units.to_integral_value():
        raise ValueError("units debe ser un entero positivo")
    target_roi = dec(inp.target_roi)
    if target_roi <= -1:
        raise ValueError("target_roi debe ser mayor que -100 %")

    out = FinancialAssessment("VALID")
    out.parameters = {
        "units": units, "buy_mode": inp.buy_mode, "sell_mode": inp.sell_mode, "venue": venue.kind,
        "owner_fee_pct": venue.owner_fee_pct,
        "profile": {
            "broker_relations": profile.broker_relations,
            "advanced_broker_relations": profile.advanced_broker_relations,
            "accounting": profile.accounting, "faction_standing": dec(profile.faction_standing),
            "corp_standing": dec(profile.corp_standing), "source": profile.source},
        "target_roi": target_roi}
    used: set[str] = set()
    if venue.kind == "UPWELL":
        used.add("R6")

    rate = broker_fee_rate(profile, venue, rules)
    tax = sales_tax_rate(profile, rules)
    out.rates = {"broker_fee": rate, "sales_tax": tax, "relist_discount": relist_discount(profile, rules)}
    if rate is None:
        return _incomplete(out, "MISSING:owner_fee_pct", used)

    buy_limit, sell_limit = inp.buy_mode == "LIMIT", inp.sell_mode == "LIMIT"
    eff_units = units
    if buy_limit:
        if inp.buy_price is None:
            return _incomplete(out, "MISSING:buy_price", used)
        buy_price = dec(inp.buy_price)
    else:
        used.add("R9")
        fill = book.buy_immediate(inp.asks, units)
        if fill.filled <= 0:
            return _incomplete(out, "NO_LIQUIDITY:asks", used)
        buy_price = fill.average_price
        eff_units = fill.filled
        if fill.shortfall > 0:
            out.warnings.append(f"PARTIAL_FILL:asks:{fill.filled}/{units}")
    if sell_limit:
        if inp.sell_price is None:
            return _incomplete(out, "MISSING:sell_price", used)
        sell_price = dec(inp.sell_price)
    else:
        used.add("R9")
        fill = book.sell_immediate(inp.bids, eff_units)
        if fill.filled <= 0:
            return _incomplete(out, "NO_LIQUIDITY:bids", used)
        sell_price = fill.average_price
        if fill.shortfall > 0:
            out.warnings.append(f"PARTIAL_FILL:bids:{fill.filled}/{eff_units}")
            eff_units = fill.filled
    if buy_price <= 0 or sell_price <= 0:
        raise ValueError("los precios deben ser positivos")

    relists = tuple(Relist(side, dec(o), dec(n)) for side, o, n in inp.relists)
    for r in relists:
        if r.side not in ("BUY", "SELL") or r.old_price <= 0 or r.new_price <= 0:
            raise ValueError("relist inválido")
    if relists:
        used.add("R8")

    trade = compute_trade(eff_units, buy_price, sell_price, buy_limit=buy_limit, sell_limit=sell_limit,
                          broker_rate=rate, profile=profile, relists=relists, rules=rules)
    out.result = {
        "units": trade.units, "buy_price": _money(buy_price), "sell_price": _money(sell_price),
        "buy_cost": _money(trade.buy_cost), "buy_fee": _money(trade.buy_fee),
        "sell_gross": _money(trade.sell_gross), "sell_fee": _money(trade.sell_fee),
        "sales_tax": _money(trade.sales_tax), "relist_fees": _money(trade.relist_fees),
        "total_costs": _money(trade.total_costs), "net_profit": _money(trade.net_profit),
        "capital_outlay": _money(trade.capital_outlay), "roi": _ratio(trade.roi), "margin": _ratio(trade.margin)}
    be = targets.min_sell_price(eff_units, trade.capital_outlay, tax_rate=tax, broker_rate=rate,
                                sell_limit=sell_limit, target_roi=Decimal(0), rules=rules)
    goal = targets.min_sell_price(eff_units, trade.capital_outlay, tax_rate=tax, broker_rate=rate,
                                  sell_limit=sell_limit, target_roi=target_roi, rules=rules)
    out.targets = {"break_even_sell_price": _money(be), "target_sell_price": _money(goal)}
    if inp.available_capital is not None:
        avail = dec(inp.available_capital)
        out.capital = {
            "available": _money(avail), "needed": _money(trade.capital_outlay),
            "affordable": avail >= trade.capital_outlay,
            "max_units": (capital.max_units(avail, buy_price, rate, rules) if buy_limit
                          else int((avail / buy_price).to_integral_value(rounding=ROUND_FLOOR)))}
    if trade.net_profit < 0:
        out.warnings.append("LOSS")
    _flag_unverified(out, used)
    return out
