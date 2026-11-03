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

export interface ItemDetail {
  status: ItemStatus;
  history: HistoryPoint[];
  latest_snapshot: Snapshot | null;
  latest_opportunities: Opportunity[];
}

export interface ItemFilters {
  status?: Status;
  categoryId?: number;
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
  if (filters.categoryId != null) params.set("category_id", String(filters.categoryId));
  if (filters.minRoi != null) params.set("min_roi", String(filters.minRoi));
  if (filters.maxRoi != null) params.set("max_roi", String(filters.maxRoi));
  if (filters.minSpread != null) params.set("min_spread", String(filters.minSpread));
  if (filters.maxSpread != null) params.set("max_spread", String(filters.maxSpread));
  if (filters.minBuy != null) params.set("min_buy", String(filters.minBuy));
  if (filters.maxBuy != null) params.set("max_buy", String(filters.maxBuy));
  if (filters.minSell != null) params.set("min_sell", String(filters.minSell));
  if (filters.maxSell != null) params.set("max_sell", String(filters.maxSell));
  if (filters.minVolume != null) params.set("min_volume", String(filters.minVolume));
  if (filters.maxVolume != null) params.set("max_volume", String(filters.maxVolume));
  params.set("sort", filters.sort ?? "volumen_diario_real");
  params.set("order", filters.order ?? "desc");
  params.set("limit", String(filters.limit ?? 50));
  params.set("offset", String(filters.offset ?? 0));
  return params.toString();
}

export const api = {
  summary: () => get<Summary>("/summary"),
  schedule: () => get<Schedule>("/schedule"),
  items: (filters: ItemFilters) => get<ItemsPage>(`/items?${buildQuery(filters)}`),
  categories: () => get<Category[]>("/categories"),
  itemDetail: (typeId: number) => get<ItemDetail>(`/items/${typeId}`),
  // Rutas /private/* — detrás de Cloudflare Access (T14). Cualquier rechazo (bloqueo
  // de Access, red) es esperado para un visitante sin sesión; quien llama decide
  // cómo tratarlo (ver el probe authPing en App.tsx).
  authPing: () => get<AuthPing>("/private/auth/ping"),
  // No es un fetch: navegación real de página, para que Cloudflare Access pueda
  // mostrar su pantalla de login (ver backend/api/private.py::login_redirect).
  authLoginUrl: "/api/private/login",
  wallet: () => get<Wallet>("/private/wallet"),
  itemRecommendation: (typeId: number) => get<Opportunity | null>(`/private/items/${typeId}/recommendation`),
  openInClient: (typeId: number) => post<OpenWindowResult>(`/private/items/${typeId}/open-in-client`),
  characterOrders: () => get<CharacterOrder[]>("/private/character-orders"),
  characterOrdersClosed: () => get<CharacterOrderClosed[]>("/private/character-orders/closed"),
  characterOrderFills: () => get<CharacterOrderFill[]>("/private/character-orders/fills"),
  refreshCharacterOrders: () => post<CharacterOrder[]>("/private/character-orders/refresh"),
  settings: () => get<AppSetting[]>("/private/settings"),
  updateSetting: (key: string, value: number) => put<AppSetting>(`/private/settings/${key}`, { value }),
  resetSettings: () => post<AppSetting[]>("/private/settings/reset"),
};
