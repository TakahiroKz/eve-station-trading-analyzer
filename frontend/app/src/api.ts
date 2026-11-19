export type Status = "POTENCIAL" | "POTENCIAL_SIN_ORDENES" | "DESCARTADO" | "EN_OBSERVACION";

export interface ItemStatus {
  type_id: number;
  name: string;
  status: Status;
  reason: string;
  spread_bruto: number;
  evaluacion_spread: string;
  liquidez: string;
  roi: number;
  best_buy: number;
  best_sell: number;
  volumen_diario_real: number;
  buy_order_count: number;
  sell_order_count: number;
  avg_daily_volume_7d: number;
  avg_daily_order_count_7d: number;
  last_evaluated_at: string;
  price_trend: number | null;
  price_trend_label: TrendLabel;
  price_trend_threshold: number | null;
  // Opportunity score 0-100 (null until the engine re-evaluates the item).
  score?: number | null;
  score_class?: ScoreClass | null;
  eligibility?: Eligibility | null;
  recommendation?: EngineAction | null;
  category_id: number | null;
  category_name: string | null;
  group_id: number | null;
  group_name: string | null;
}

export interface ItemsPage {
  items: ItemStatus[];
  total: number;
  limit: number;
  offset: number;
  capital?: number | null; // capital (snapped by the server) the scores were computed for; null = reference
}

export interface Category {
  category_id: number;
  category_name: string;
}

export interface Summary {
  counts: Partial<Record<Status, number>>;
  total: number;
  last_evaluated_at: string | null;
}

export interface Schedule {
  market_next_run: string | null;
  positions_next_run: string | null;
}

export interface HistoryPoint {
  date: string;
  avg_price: number;
  highest: number;
  lowest: number;
  volume: number;
  order_count: number;
}

export interface Snapshot {
  captured_at: string;
  best_buy: number | null;
  best_sell: number | null;
  buy_volume: number | null;
  sell_volume: number | null;
  buy_order_count: number;
  sell_order_count: number;
  // Order-book depth of the whole region (null in older snapshots or when that side has no orders).
  buy_depth_5pct?: number | null;
  sell_depth_5pct?: number | null;
  buy_gap_bp?: number | null;
  sell_gap_bp?: number | null;
  buy_top_permille?: number | null;
  sell_top_permille?: number | null;
}

export interface Opportunity {
  evaluated_at: string;
  buy: number;
  sell: number;
  volumen_deseado: number;
  volumen_diario_real: number;
  beneficio: number;
  spread_bruto: number;
  precio_min_venta: number;
  roi: number;
  evaluacion_spread: string;
  posicion_vs_volumen: number;
  liquidez: string;
  recomendacion: string;
  unidades_sugeridas: number | null;
}

export type ScoreClass = "EXCELLENT" | "HIGH" | "MODERATE" | "LOW" | "DISCARDED";
export type Eligibility = "NO_ELIGIBLE" | "ELIGIBLE" | "RECOMMENDED";
export type EngineAction = "BUY_CANDIDATE" | "WAIT" | "REJECT";

export interface ScoreFactor {
  key: "profitability" | "liquidity" | "volume" | "book" | "stability" | "capital";
  label: string;
  points: number;
  max: number;
  score: number;
  value: string;
  note: string;
  code: string;
  metrics: Record<string, number | null>;
}

export interface ScoreCap {
  code: string;
  limit: number | null;
  roi?: number;
  note: string;
}

export interface ScoreChange {
  code: string;
  current: number | string | null;
  needed: number | string | null;
}

export interface Assessment {
  algorithm_version: string;
  stored_version: string;
  config_changed: boolean;
  evaluated_at: string;
  data_age_min: number | null;
  score: {
    total: number | null;
    classification: ScoreClass;
    version: string;
    reference: Record<string, number | null>;
    factors: ScoreFactor[];
    caps: ScoreCap[];
  };
  eligibility: { status: Eligibility; failed_filters: string[]; passed_filters: string[] };
  recommendation: { action: EngineAction; reason_codes: string[]; to_change: ScoreChange[] };
  reference: Record<string, number | null>;
}

// Units to buy for a capital (position = capital x position_pct); computed by the server with the engine's own math.
export interface UnitRecommendation {
  capital: number;
  position_pct: number;
  posicion_isk: number;
  volumen_deseado: number;
  unidades_sugeridas: number;
  recomendacion: string;
  action: EngineAction | null;
  blocked_by: string[];
  precio_unidad_isk: number;
  alcanza: boolean; // false: one unit costs more than the position
  inversion_isk: number;
  beneficio_neto_isk: number;
  dias_rotacion: number | null;
}

export interface ItemDetail {
  status: ItemStatus;
  recommendation?: UnitRecommendation | null;
  history: HistoryPoint[];
  latest_snapshot: Snapshot | null;
  latest_opportunities: Opportunity[];
  assessment?: Assessment | null;
}

export type TrendLabel = "up" | "down" | "flat" | "lowliq" | "nodata";

export interface Market {
  market_id: string;
  name: string;
  region_id: number;
  counts: Partial<Record<Status, number>>;
  total: number;
  last_evaluated_at: string | null;
}

export interface ItemFilters {
  market?: string;
  status?: Status;
  categoryId?: number;
  q?: string;
  minRoi?: number;
  maxRoi?: number;
  minSpread?: number;
  maxSpread?: number;
  minBuy?: number;
  maxBuy?: number;
  minSell?: number;
  maxSell?: number;
  minVolume?: number;
  maxVolume?: number;
  trend?: TrendLabel;
  minScore?: number;
  eligibility?: Eligibility;
  capital?: number; // ISK: the server recomputes the score for this capital
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export interface OpenWindowResult {
  opened: boolean;
  detail: string;
}

export interface CharacterOrder {
  order_id: number;
  type_id: number;
  name: string;
  is_buy_order: boolean;
  price: number;
  volume_remain: number;
  volume_total: number;
  is_undercut: boolean;
  region_id: number;
  orders_ahead: number;
  price_gap: number;
  best_price: number | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface CharacterOrderClosed {
  order_id: number;
  type_id: number;
  name: string;
  is_buy_order: boolean;
  price: number;
  final_state: string;
  closed_at: string;
}

export interface CharacterOrderFill {
  id: number;
  order_id: number;
  type_id: number;
  name: string;
  is_buy_order: boolean;
  price: number;
  filled_units: number;
  volume_remain: number;
  filled_at: string;
}

export interface AppSetting {
  key: string;
  category: string;
  label: string;
  description: string;
  value: number;
  default_value: number;
  updated_at: string;
}

export interface AuthPing {
  ok: boolean;
}

export interface Wallet {
  wallet_balance: number | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} en ${path}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText} en ${path}`);
  }
  return res.json() as Promise<T>;
}

async function put<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText} en ${path}`);
  }
  return res.json() as Promise<T>;
}

function buildQuery(filters: ItemFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.market) params.set("market", filters.market);
  if (filters.categoryId != null) params.set("category_id", String(filters.categoryId));
  if (filters.q) params.set("q", filters.q);
  if (filters.minRoi != null) params.set("min_roi", String(filters.minRoi));
  if (filters.maxRoi != null) params.set("max_roi", String(filters.maxRoi));
  if (filters.minSpread != null) params.set("min_spread", String(filters.minSpread));
  if (filters.maxSpread != null) params.set("max_spread", String(filters.maxSpread));
  if (filters.minBuy != null) params.set("min_buy", String(filters.minBuy));
  if (filters.maxBuy != null) params.set("max_buy", String(filters.maxBuy));
  if (filters.minSell != null) params.set("min_sell", String(filters.minSell));
  if (filters.maxSell != null) params.set("max_sell", String(filters.maxSell));
  if (filters.trend) params.set("trend", filters.trend);
  if (filters.minScore != null) params.set("min_score", String(filters.minScore));
  if (filters.eligibility) params.set("eligibility", filters.eligibility);
  if (filters.capital != null) params.set("capital", String(filters.capital));
  if (filters.minVolume != null) params.set("min_volume", String(filters.minVolume));
  if (filters.maxVolume != null) params.set("max_volume", String(filters.maxVolume));
  params.set("sort", filters.sort ?? "volumen_diario_real");
  params.set("order", filters.order ?? "desc");
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

// `/summary?market=amarr`; sin mercado, el servidor usa el predeterminado (Jita).
function withMarket(path: string, market?: string): string {
  return market ? `${path}?market=${encodeURIComponent(market)}` : path;
}

export const api = {
  markets: () => get<Market[]>("/markets"),
  summary: (market?: string) => get<Summary>(withMarket("/summary", market)),
  schedule: () => get<Schedule>("/schedule"),
  items: (filters: ItemFilters) => get<ItemsPage>(`/items?${buildQuery(filters)}`),
  categories: (market?: string) => get<Category[]>(withMarket("/categories", market)),
  itemDetail: (typeId: number, market?: string, capital?: number) => {
    const path = withMarket(`/items/${typeId}`, market);
    return get<ItemDetail>(capital == null ? path : `${path}${path.includes("?") ? "&" : "?"}capital=${capital}`);
  },
  // Rutas /private/* — detrás de Cloudflare Access (T14). Cualquier rechazo (bloqueo
  // de Access, red) es esperado para un visitante sin sesión; quien llama decide
  // cómo tratarlo (ver el probe authPing en App.tsx).
  authPing: () => get<AuthPing>("/private/auth/ping"),
  // No es un fetch: navegación real de página, para que Cloudflare Access pueda
  // mostrar su pantalla de login (ver backend/api/private.py::login_redirect).
  authLoginUrl: "/api/private/login",
  wallet: () => get<Wallet>("/private/wallet"),
  itemRecommendation: (typeId: number, market?: string) =>
    get<Opportunity | null>(withMarket(`/private/items/${typeId}/recommendation`, market)),
  openInClient: (typeId: number) => post<OpenWindowResult>(`/private/items/${typeId}/open-in-client`),
  characterOrders: () => get<CharacterOrder[]>("/private/character-orders"),
  characterOrdersClosed: () => get<CharacterOrderClosed[]>("/private/character-orders/closed"),
  characterOrderFills: () => get<CharacterOrderFill[]>("/private/character-orders/fills"),
  refreshCharacterOrders: () => post<CharacterOrder[]>("/private/character-orders/refresh"),
  settings: () => get<AppSetting[]>("/private/settings"),
  updateSetting: (key: string, value: number) => put<AppSetting>(`/private/settings/${key}`, { value }),
  resetSettings: () => post<AppSetting[]>("/private/settings/reset"),
};
