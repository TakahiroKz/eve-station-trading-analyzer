from typing import Literal

from pydantic import BaseModel

Status = Literal["POTENCIAL", "POTENCIAL_SIN_ORDENES", "DESCARTADO", "EN_OBSERVACION"]


class ItemStatusOut(BaseModel):
    type_id: int
    name: str
    status: Status
    reason: str
    spread_bruto: float
    evaluacion_spread: str
    liquidez: str
    roi: float
    best_buy: float
    best_sell: float
    volumen_diario_real: float
    buy_order_count: int
    sell_order_count: int
    avg_daily_volume_7d: float
    avg_daily_order_count_7d: float
    last_evaluated_at: str
    category_id: int | None = None
    category_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None


class ItemsPageOut(BaseModel):
    items: list[ItemStatusOut]
    total: int
    limit: int
    offset: int


class CategoryOut(BaseModel):
    category_id: int
    category_name: str


class SummaryOut(BaseModel):
    counts: dict[str, int]
    total: int
    last_evaluated_at: str | None


class WalletOut(BaseModel):
    wallet_balance: float | None


class AuthPingOut(BaseModel):
    ok: bool = True


class HistoryPointOut(BaseModel):
    date: str
    avg_price: float
    highest: float
    lowest: float
    volume: int
    order_count: int


class SnapshotOut(BaseModel):
    captured_at: str
    best_buy: float | None
    best_sell: float | None
    buy_volume: int | None
    sell_volume: int | None
    buy_order_count: int
    sell_order_count: int


class OpportunityOut(BaseModel):
    evaluated_at: str
    buy: float
    sell: float
    volumen_deseado: float
    volumen_diario_real: float
    beneficio: float
    spread_bruto: float
    precio_min_venta: float
    roi: float
    evaluacion_spread: str
    posicion_vs_volumen: float
    liquidez: str
    recomendacion: str
    unidades_sugeridas: int | None = None


class ItemDetailOut(BaseModel):
    status: ItemStatusOut
    history: list[HistoryPointOut]
    latest_snapshot: SnapshotOut | None
    latest_opportunities: list[OpportunityOut]


class StatusChangeOut(BaseModel):
    type_id: int
    name: str
    previous_status: str | None
    new_status: str
    changed_at: str
    reason: str


class OpenWindowOut(BaseModel):
    opened: bool
    detail: str


class ScheduleOut(BaseModel):
    market_next_run: str | None
    positions_next_run: str | None


class CharacterOrderOut(BaseModel):
    order_id: int
    type_id: int
    name: str
    is_buy_order: bool
    price: float
    volume_remain: int
    volume_total: int
    is_undercut: bool
    region_id: int
    orders_ahead: int
    price_gap: float
    best_price: float | None
    first_seen_at: str
    last_seen_at: str


class CharacterOrderFillOut(BaseModel):
    id: int
    order_id: int
    type_id: int
    name: str
    is_buy_order: bool
    price: float
    filled_units: int
    volume_remain: int
    filled_at: str


class CharacterOrderClosedOut(BaseModel):
    order_id: int
    type_id: int
    name: str
    is_buy_order: bool
    price: float
    final_state: str
    closed_at: str


class AppSettingOut(BaseModel):
    key: str
    category: str
    label: str
    description: str
    value: float
    default_value: float
    updated_at: str


class AppSettingUpdateIn(BaseModel):
    value: float
