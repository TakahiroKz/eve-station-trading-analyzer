"""Simulador financiero (fase 4 de EF-02): evaluar y comparar operaciones con el motor de comisiones y guardar escenarios.

/api/finance/* es público y sin estado (un visitante usa el perfil por defecto o uno que escribe a mano); con sesión se
puede usar el perfil real del jugador (profile_mode="mine") y su wallet. Los escenarios guardados viven en users.db y son
una foto reproducible: llevan el libro de órdenes y el perfil que se usaron, no una referencia a datos que cambian.
"""
import logging
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.api.auth import NO_STORE
from backend.api.me import _loads, _session
from backend.api.security import check_same_origin
from finance.assessment import TradeInput, evaluate
from finance.fees import Profile, Venue
from finance.hubs import HUB_BY_MARKET, Hub
from finance.rules import ENGINE_VERSION, RULES_VERSION
from finance.user_profile import build_profile
from ingestion import esi_profile
from ingestion.station_book import BookUnavailable, fetch_station_book
from storage import users_db
from storage.db import MARKETS_SEED

logger = logging.getLogger(__name__)
router = APIRouter(tags=["finance"])
REGION_BY_MARKET = {row[0]: row[2] for row in MARKETS_SEED}
MAX_LEVELS = 200
MAX_COMPARE = 6

Money = Annotated[Decimal, Field(gt=0, le=Decimal("1e13"), allow_inf_nan=False)]
Level = tuple[Money, Annotated[int, Field(ge=1, le=10**12)]]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelistIn(_Strict):
    side: Literal["BUY", "SELL"]
    old_price: Money
    new_price: Money


class ManualProfileIn(_Strict):
    broker_relations: int = Field(2, ge=0, le=5)
    advanced_broker_relations: int = Field(0, ge=0, le=5)
    accounting: int = Field(0, ge=0, le=5)
    faction_standing: float = Field(0, ge=-10, le=10, allow_inf_nan=False)
    corp_standing: float = Field(0, ge=-10, le=10, allow_inf_nan=False)


class EvaluateIn(_Strict):
    market_id: str = Field("jita", max_length=20)
    type_id: int | None = Field(None, ge=1, le=10**9)
    units: int = Field(ge=1, le=10**12)
    buy_mode: Literal["LIMIT", "IMMEDIATE"] = "LIMIT"
    buy_price: Money | None = None
    sell_mode: Literal["LIMIT", "IMMEDIATE"] = "LIMIT"
    sell_price: Money | None = None
    venue: Literal["NPC", "UPWELL"] = "NPC"
    owner_fee_percent: float | None = Field(None, ge=0, le=20, allow_inf_nan=False)
    relists: list[RelistIn] = Field(default_factory=list, max_length=20)
    target_roi_percent: float = Field(0, ge=-99, le=1000, allow_inf_nan=False)
    available_capital: Decimal | None = Field(None, ge=0, le=Decimal("1e15"), allow_inf_nan=False)
    use_wallet: bool = False
    profile_mode: Literal["default", "mine", "manual"] = "default"
    manual_profile: ManualProfileIn | None = None
    use_live_book: bool = False
    asks: list[Level] = Field(default_factory=list, max_length=MAX_LEVELS)
    bids: list[Level] = Field(default_factory=list, max_length=MAX_LEVELS)

    @model_validator(mode="after")
    def _coherent(self):
        if self.profile_mode == "manual" and self.manual_profile is None:
            raise ValueError("profile_mode manual necesita manual_profile")
        if self.use_wallet and self.profile_mode != "mine":
            raise ValueError("use_wallet solo con profile_mode mine")
        if self.use_live_book and (self.venue != "NPC" or self.type_id is None):
            raise ValueError("el libro en vivo solo existe para estaciones NPC y necesita type_id")
        return self


class NamedScenario(_Strict):
    name: str = Field(min_length=1, max_length=60)
    request: EvaluateIn


class CompareIn(_Strict):
    scenarios: list[NamedScenario] = Field(min_length=2, max_length=MAX_COMPARE)


class SaveIn(NamedScenario):
    pass


def _json(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=NO_STORE)


def _hub(market_id: str) -> Hub:
    hub = HUB_BY_MARKET.get(market_id)
    if hub is None:
        raise HTTPException(422, f"Mercado desconocido: {market_id}", headers=NO_STORE)
    return hub


def _resolve_profile(req: EvaluateIn, hub: Hub, request: Request, now) -> tuple[Profile, dict, Decimal | None]:
    """(perfil del motor, descripción de lo usado, capital del wallet si se pidió y hay)."""
    if req.profile_mode == "default":
        return Profile(source="MANUAL"), {"mode": "default", "source": "DEFAULT"}, None
    if req.profile_mode == "manual":
        m = req.manual_profile
        profile = Profile(m.broker_relations, m.advanced_broker_relations, m.accounting, Decimal(str(m.faction_standing)),
                          Decimal(str(m.corp_standing)), source="MANUAL")
        return profile, {"mode": "manual", "source": "MANUAL"}, None
    conn, user, client_id, secret = _session(request)
    try:
        if req.use_wallet:
            esi_profile.sync_profile(conn, user["character_id"], client_id, secret, now, want_wallet=True)
        row = users_db.get_profile(conn, user["character_id"])
        profile, _skills, _standings = build_profile(
            hub, _loads(row["skills_json"]) if row else None, _loads(row["standings_json"]) if row else None,
            (_loads(row["override_json"]) if row else None) or {})
        wallet = Decimal(row["wallet_isk"]) if (req.use_wallet and row and row["wallet_isk"]) else None
        return profile, {"mode": "mine", "source": profile.source}, wallet
    finally:
        conn.close()


def _profile_info(profile: Profile, info: dict) -> dict:
    return {**info, "broker_relations": profile.broker_relations,
            "advanced_broker_relations": profile.advanced_broker_relations, "accounting": profile.accounting,
            "faction_standing": str(profile.faction_standing), "corp_standing": str(profile.corp_standing)}


def run(req: EvaluateIn, request: Request) -> dict:
    """Evalúa una petición y devuelve resultado + lo realmente usado (perfil y libro), listo para guardarse como foto."""
    hub = _hub(req.market_id)
    now = users_db.utcnow()
    profile, info, wallet = _resolve_profile(req, hub, request, now)
    asks, bids, book_info = list(req.asks), list(req.bids), None
    if req.use_live_book:
        try:
            book = fetch_station_book(REGION_BY_MARKET[req.market_id], hub.station_id, req.type_id)
        except BookUnavailable as exc:
            logger.warning("Libro de órdenes no disponible: %s", exc)
            raise HTTPException(503, "El libro de órdenes no está disponible ahora mismo.", headers=NO_STORE) from exc
        asks = [(Decimal(p), int(v)) for p, v in book["asks"]]
        bids = [(Decimal(p), int(v)) for p, v in book["bids"]]
        book_info = {"station_id": hub.station_id, "station": hub.station_name, "fetched_at": book["fetched_at"],
                     "cached": book["cached"], "ask_levels": len(asks), "bid_levels": len(bids)}
    capital = req.available_capital if req.available_capital is not None else wallet
    owner = Decimal(str(req.owner_fee_percent)) / 100 if req.owner_fee_percent is not None else None
    try:
        assessment = evaluate(TradeInput(
            units=req.units, buy_mode=req.buy_mode, buy_price=req.buy_price, asks=tuple(asks),
            sell_mode=req.sell_mode, sell_price=req.sell_price, bids=tuple(bids), profile=profile,
            venue=Venue(req.venue, owner), relists=tuple((r.side, r.old_price, r.new_price) for r in req.relists),
            target_roi=Decimal(str(req.target_roi_percent)) / 100, available_capital=capital))
    except ValueError as exc:
        raise HTTPException(422, str(exc), headers=NO_STORE) from exc
    if req.use_wallet and req.available_capital is None and wallet is None:
        assessment.warnings.append("WALLET_UNAVAILABLE")
    out = assessment.to_dict()
    out["rates"] = {k: None if v is None else format(Decimal(v).normalize(), "f")             # 0.0240 → 0.024
                    for k, v in out["rates"].items()}
    return {"assessment": out, "market_id": req.market_id, "station": hub.station_name,
            "profile": _profile_info(profile, info), "book": book_info,
            "capital_source": "MANUAL" if req.available_capital is not None else ("WALLET" if wallet is not None else None),
            "_asks": asks, "_bids": bids, "_profile": profile}


def _public(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}


@router.post("/api/finance/evaluate")
def evaluate_route(body: EvaluateIn, request: Request):
    check_same_origin(request)
    return _json(_public(run(body, request)))


@router.post("/api/finance/compare")
def compare_route(body: CompareIn, request: Request):
    check_same_origin(request)
    results = []
    for scenario in body.scenarios:
        out = _public(run(scenario.request, request))
        out["name"] = scenario.name
        results.append(out)

    def roi(item):
        result = item["assessment"]["result"]
        return Decimal(result["roi"]) if item["assessment"]["calculation_status"] == "VALID" and result else None
    ranked = sorted((r for r in results if roi(r) is not None), key=roi, reverse=True)
    return _json({"results": results, "ranking": [r["name"] for r in ranked]})


def snapshot_request(req: EvaluateIn, result: dict) -> dict:
    """La petición convertida en foto: libro y perfil explícitos, sin llamadas en vivo; se puede volver a evaluar igual."""
    profile: Profile = result["_profile"]
    snap = req.model_dump(mode="json")
    snap.update(
        use_live_book=False, use_wallet=False, profile_mode="manual",
        manual_profile={"broker_relations": profile.broker_relations,
                        "advanced_broker_relations": profile.advanced_broker_relations, "accounting": profile.accounting,
                        "faction_standing": float(profile.faction_standing), "corp_standing": float(profile.corp_standing)},
        asks=[[str(p), int(v)] for p, v in result["_asks"]], bids=[[str(p), int(v)] for p, v in result["_bids"]])
    if result["capital_source"] == "WALLET":
        snap["available_capital"] = result["assessment"]["capital"].get("available")
    return snap


@router.post("/api/me/scenarios")
def save_scenario(body: SaveIn, request: Request):
    check_same_origin(request)
    conn, user, _client_id, _secret = _session(request)
    try:
        result = run(body.request, request)
        snapshot = snapshot_request(body.request, result)
        meta = {"market_id": body.request.market_id, "profile_mode": body.request.profile_mode,
                "book": result["book"], "capital_source": result["capital_source"]}
        new_id = users_db.add_scenario(conn, user["character_id"], body.name.strip(), {"request": snapshot, "meta": meta},
                                       result["assessment"], ENGINE_VERSION, RULES_VERSION, users_db.utcnow())
        if new_id is None:
            raise HTTPException(409, f"Tienes el máximo de {users_db.MAX_SCENARIOS} escenarios guardados.", headers=NO_STORE)
        conn.commit()
        return _json({"id": new_id}, 201)
    finally:
        conn.close()


@router.get("/api/me/scenarios")
def list_my_scenarios(request: Request):
    conn, user, _client_id, _secret = _session(request)
    try:
        rows = users_db.list_scenarios(conn, user["character_id"])
        out = []
        for row in rows:
            stored = _loads(row["request_json"]) or {}
            out.append({"id": row["id"], "name": row["name"], "created_at": row["created_at"],
                        "engine_version": row["engine_version"], "rules_version": row["rules_version"],
                        "request": stored.get("request"), "meta": stored.get("meta"), "result": _loads(row["result_json"])})
        return _json({"scenarios": out, "max": users_db.MAX_SCENARIOS})
    finally:
        conn.close()


@router.delete("/api/me/scenarios/{scenario_id}")
def delete_my_scenario(scenario_id: int, request: Request):
    check_same_origin(request)
    conn, user, _client_id, _secret = _session(request)
    try:
        if not users_db.delete_scenario(conn, user["character_id"], scenario_id):
            raise HTTPException(404, "Escenario no encontrado.", headers=NO_STORE)
        conn.commit()
        return _json({"ok": True})
    finally:
        conn.close()
