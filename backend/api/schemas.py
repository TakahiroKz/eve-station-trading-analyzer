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
    price_trend: float | None = None
    price_trend_label: str = "nodata"
    price_trend_threshold: float | None = None
    # Puntaje 0-100 explicable (None hasta que el motor reevalúa el ítem). El desglose completo va en el detalle.
    score: int | None = None
    score_class: Literal["EXCELLENT", "HIGH", "MODERATE", "LOW", "DISCARDED"] | None = None
    eligibility: Literal["NO_ELIGIBLE", "ELIGIBLE", "RECOMMENDED"] | None = None
    recommendation: Literal["BUY_CANDIDATE", "WAIT", "REJECT"] | None = None
    category_id: int | None = None
    category_name: str | None = None
    group_id: int | None = None
    group_name: str | None = None


class ItemsPageOut(BaseModel):
    items: list[ItemStatusOut]
    total: int
    limit: int
    offset: int
    # Capital (ISK) con el que se recalculó el puntaje de estos ítems; None = el de referencia guardado.
    capital: float | None = None
    # Comisiones del jugador aplicadas (profile=mine): fuente, broker fee y sales tax; None = valores de referencia.
    profile: dict | None = None


class CategoryOut(BaseModel):
    category_id: int
    category_name: str


class MarketOut(BaseModel):
    market_id: str
    name: str
    region_id: int
    counts: dict[str, int]
    total: int
    last_evaluated_at: str | None


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
    # Profundidad del libro de la región (None en snapshots anteriores a su registro o sin órdenes de ese lado).
    buy_depth_5pct: int | None = None
    sell_depth_5pct: int | None = None
    buy_gap_bp: int | None = None
    sell_gap_bp: int | None = None
    buy_top_permille: int | None = None
    sell_top_permille: int | None = None


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


class UnitRecommendationOut(BaseModel):
    """Recomendación de unidades para un capital: la misma cuenta del motor (evaluar_oportunidad) con la posición
    = capital x % por posición. Es lo que lee el visitante en el detalle; el propietario con sesión y sin capital
    elegido ve la suya en vivo con su wallet (/api/private/items/{id}/recommendation)."""
    capital: float
    position_pct: float
    posicion_isk: float
    volumen_deseado: float
    unidades_sugeridas: int
    recomendacion: str
    action: Literal["BUY_CANDIDATE", "WAIT", "REJECT"] | None = None
    blocked_by: list[str] = []
    precio_unidad_isk: float          # lo que cuesta una unidad (precio de compra con comisión)
    alcanza: bool                     # ¿la posición alcanza al menos para una unidad?
    inversion_isk: float
    beneficio_neto_isk: float
    dias_rotacion: float | None = None


class ItemDetailOut(BaseModel):
    status: ItemStatusOut
    history: list[HistoryPointOut]
    latest_snapshot: SnapshotOut | None
    latest_opportunities: list[OpportunityOut]
    recommendation: UnitRecommendationOut | None = None
    # Explicación del puntaje: factores (puntos / máximo / valor / frase), topes, filtros, códigos de motivo y
    # "qué tendría que cambiar". Calculada en el backend; el frontend solo la muestra. None si aún no hay puntaje.
    assessment: dict | None = None
    profile: dict | None = None
    # Último día de histórico guardado del mercado, el siguiente y cuándo lo publica la ESI; "late" = falta un día ya publicado.
    history_info: dict | None = None


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
