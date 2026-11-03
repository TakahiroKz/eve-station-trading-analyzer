import { useEffect, useState } from "react";
import {
  api, type AppSetting, type Category, type CharacterOrder, type CharacterOrderClosed,
  type CharacterOrderFill, type ItemDetail, type ItemFilters, type ItemStatus, type Opportunity,
  type Schedule, type Status, type Summary,
} from "./api";
import "./App.css";

const CLOSED_STATE_LABEL: Record<string, string> = {
  completada: "Completada",
  expirada: "Expirada",
  cancelada: "Cancelada",
  cerrada: "Cerrada",
};

const TABS: { key: Status; label: string }[] = [
  { key: "POTENCIAL", label: "Potencial" },
  { key: "POTENCIAL_SIN_ORDENES", label: "Sin órdenes" },
  { key: "EN_OBSERVACION", label: "En observación" },
  { key: "DESCARTADO", label: "Descartado" },
];

const PAGE_SIZE = 50;
const TRACKED_REGION_ID = 10000002; // The Forge / Jita

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "volumen_diario_real", label: "Volumen diario" },
  { value: "roi", label: "ROI" },
  { value: "spread_bruto", label: "Spread" },
  { value: "best_buy", label: "Precio compra" },
  { value: "best_sell", label: "Precio venta" },
  { value: "avg_daily_order_count_7d", label: "Operaciones 7d" },
  { value: "name", label: "Nombre" },
];

interface FilterForm {
  categoryId: string;
  minRoi: string;
  maxRoi: string;
  minSpread: string;
  maxSpread: string;
  minBuy: string;
  maxBuy: string;
  minSell: string;
  maxSell: string;
  minVolume: string;
  maxVolume: string;
}

const EMPTY_FILTERS: FilterForm = {
  categoryId: "", minRoi: "", maxRoi: "", minSpread: "", maxSpread: "",
  minBuy: "", maxBuy: "", minSell: "", maxSell: "", minVolume: "", maxVolume: "",
};

function formatIsk(value: number | null | undefined) {
  if (value == null) return "—";
  // maximumFractionDigits: 2 porque el ISK no tiene más precisión que eso — cubre
  // sin redondear a cero los precios chicos (ítems de pocas ISK con decimales
  // significativos), sin agregar ".00" de más en los enteros (no hay minimum).
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 }).format(value);
}

function formatIskValue(value: number | null | undefined) {
  if (value == null) return "—";
  return `${formatIsk(value)} ISK`;
}

function formatPct(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatCountdown(target: string | null, now: Date): string {
  if (!target) return "sin tarea programada";
  const diffMs = new Date(target).getTime() - now.getTime();
  if (diffMs <= 0) return "en curso…";
  const totalSeconds = Math.floor(diffMs / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const parts: string[] = [];
  if (h > 0) parts.push(`${h}h`);
  if (h > 0 || m > 0) parts.push(`${m}m`);
  parts.push(`${s}s`);
  return parts.join(" ");
}

function toFilters(form: FilterForm): Partial<ItemFilters> {
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));
  return {
    categoryId: num(form.categoryId),
    minRoi: num(form.minRoi) != null ? num(form.minRoi)! / 100 : undefined,
    maxRoi: num(form.maxRoi) != null ? num(form.maxRoi)! / 100 : undefined,
    minSpread: num(form.minSpread) != null ? num(form.minSpread)! / 100 : undefined,
    maxSpread: num(form.maxSpread) != null ? num(form.maxSpread)! / 100 : undefined,
    minBuy: num(form.minBuy),
    maxBuy: num(form.maxBuy),
    minSell: num(form.minSell),
    maxSell: num(form.maxSell),
    minVolume: num(form.minVolume),
    maxVolume: num(form.maxVolume),
  };
}

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tab, setTab] = useState<Status>("POTENCIAL");
  const [filterForm, setFilterForm] = useState<FilterForm>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<Partial<ItemFilters>>({});
  const [showFilters, setShowFilters] = useState(false);
  const [sortField, setSortField] = useState("volumen_diario_real");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<ItemStatus[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ItemDetail | null>(null);
  const [openWindowMsg, setOpenWindowMsg] = useState<string | null>(null);
  const [view, setView] = useState<"screener" | "orders" | "settings">("screener");
  const [characterOrders, setCharacterOrders] = useState<CharacterOrder[]>([]);
  const [closedOrders, setClosedOrders] = useState<CharacterOrderClosed[]>([]);
  const [orderFills, setOrderFills] = useState<CharacterOrderFill[]>([]);
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersRefreshing, setOrdersRefreshing] = useState(false);
  const [orderSearch, setOrderSearch] = useState("");
  const [orderRegion, setOrderRegion] = useState<"all" | "tracked" | "other">("all");
  const [orderUndercutOnly, setOrderUndercutOnly] = useState(false);
  const [orderSort, setOrderSort] = useState<"name" | "price" | "value">("name");
  const [orderSortDir, setOrderSortDir] = useState<"asc" | "desc">("asc");
  const [showOrderFilters, setShowOrderFilters] = useState(false);
  const [settings, setSettings] = useState<AppSetting[]>([]);
  const [settingsForm, setSettingsForm] = useState<Record<string, string>>({});
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsResetting, setSettingsResetting] = useState(false);
  const [settingsMsg, setSettingsMsg] = useState<string | null>(null);
  // Fail-closed: sin sesión confirmada de Cloudflare Access hasta que el probe
  // responda (T14) — ver el useEffect de authPing más abajo.
  const [authenticated, setAuthenticated] = useState(false);
  const [wallet, setWallet] = useState<number | null>(null);
  const [recommendation, setRecommendation] = useState<Opportunity | null>(null);

  const [now, setNow] = useState(new Date());

  useEffect(() => {
    api.summary().then(setSummary).catch((e) => setError(String(e)));
    api.categories().then(setCategories).catch(() => {});
  }, []);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const checkAuth = () =>
      api.authPing().then(() => setAuthenticated(true)).catch(() => setAuthenticated(false));
    checkAuth();
    // Repetido para notar una sesión de Access vencida sin necesidad de recargar.
    const id = setInterval(checkAuth, 60_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    // Si se pierde la sesión estando en una vista privada, volver al Screener.
    if (!authenticated && view !== "screener") setView("screener");
  }, [authenticated, view]);

  useEffect(() => {
    if (!authenticated) { setWallet(null); return; }
    api.wallet().then((w) => setWallet(w.wallet_balance)).catch(() => setWallet(null));
  }, [authenticated]);

  useEffect(() => {
    if (!authenticated || view !== "orders") return;
    setOrdersLoading(true);
    setError(null);
    Promise.all([api.characterOrders(), api.characterOrdersClosed(), api.characterOrderFills()])
      .then(([active, closed, fills]) => {
        setCharacterOrders(active);
        setClosedOrders(closed);
        setOrderFills(fills);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setOrdersLoading(false));
  }, [authenticated, view]);

  useEffect(() => {
    // Vive en la cabecera fija, visible en cualquier vista — no solo en Mis Órdenes.
    const loadSchedule = () => api.schedule().then(setSchedule).catch(() => {});
    loadSchedule();
    // Los timers de abajo cuentan regresivamente sobre este valor con el reloj `now`,
    // pero el disparo real (Windows) puede adelantarse por su cuenta — se repregunta
    // cada minuto para que no se quede mostrando "en curso…" indefinidamente.
    const id = setInterval(loadSchedule, 60_000);
    return () => clearInterval(id);
  }, []);

  function loadSettings() {
    setSettingsLoading(true);
    setSettingsMsg(null);
    return api
      .settings()
      .then((rows) => {
        setSettings(rows);
        setSettingsForm(Object.fromEntries(rows.map((s) => [s.key, String(s.value)])));
      })
      .catch((e) => setSettingsMsg(String(e)))
      .finally(() => setSettingsLoading(false));
  }

  useEffect(() => {
    if (!authenticated || view !== "settings") return;
    loadSettings();
  }, [authenticated, view]);

  function saveSettings() {
    const changed = settings.filter((s) => {
      const formValue = Number(settingsForm[s.key]);
      return !Number.isNaN(formValue) && formValue !== s.value;
    });
    const invalid = settings.some((s) => Number.isNaN(Number(settingsForm[s.key])) || Number(settingsForm[s.key]) < 0);
    if (invalid) {
      setSettingsMsg("Todos los valores deben ser números mayores o iguales a 0.");
      return;
    }
    if (changed.length === 0) {
      setSettingsMsg("No hay cambios para guardar.");
      return;
    }

    setSettingsSaving(true);
    setSettingsMsg(null);
    Promise.all(changed.map((s) => api.updateSetting(s.key, Number(settingsForm[s.key]))))
      .then(() => {
        setSettingsMsg(
          `Guardado (${changed.length} ${changed.length === 1 ? "parámetro" : "parámetros"}). ` +
          "Se aplica en la próxima corrida de cada motor.",
        );
        return loadSettings();
      })
      .catch((e) => setSettingsMsg(String(e)))
      .finally(() => setSettingsSaving(false));
  }

  function resetSettings() {
    setSettingsResetting(true);
    setSettingsMsg(null);
    api
      .resetSettings()
      .then((rows) => {
        setSettings(rows);
        setSettingsForm(Object.fromEntries(rows.map((s) => [s.key, String(s.value)])));
        setSettingsMsg("Todos los parámetros volvieron a su valor por defecto.");
      })
      .catch((e) => setSettingsMsg(String(e)))
      .finally(() => setSettingsResetting(false));
  }

  const settingsByCategory = settings.reduce<Record<string, AppSetting[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {});

  function refreshOrders() {
    setOrdersRefreshing(true);
    setError(null);
    api
      .refreshCharacterOrders()
      .then((active) => {
        setCharacterOrders(active);
        return api.characterOrdersClosed();
      })
      .then((closed) => {
        setClosedOrders(closed);
        return api.characterOrderFills();
      })
      .then(setOrderFills)
      .then(() => Promise.all([api.summary(), api.wallet()]))
      .then(([s, w]) => {
        setSummary(s);
        setWallet(w.wallet_balance);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setOrdersRefreshing(false));
  }

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .items({
        status: tab, ...appliedFilters, sort: sortField, order: sortOrder,
        limit: PAGE_SIZE, offset: page * PAGE_SIZE,
      })
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tab, appliedFilters, sortField, sortOrder, page]);

  function openItem(typeId: number) {
    setOpenWindowMsg(null);
    setRecommendation(null);
    api.itemDetail(typeId).then(setSelected).catch((e) => setError(String(e)));
    if (authenticated) {
      api.itemRecommendation(typeId).then(setRecommendation).catch(() => setRecommendation(null));
    }
  }

  function openInClient(typeId: number) {
    setOpenWindowMsg("Abriendo…");
    api
      .openInClient(typeId)
      .then((res) => setOpenWindowMsg(res.detail))
      .catch((e) => setOpenWindowMsg(String(e)));
  }

  function applyFilters() {
    setAppliedFilters(toFilters(filterForm));
    setPage(0);
  }

  function clearFilters() {
    setFilterForm(EMPTY_FILTERS);
    setAppliedFilters({});
    setPage(0);
  }

  const undercutCount = characterOrders.filter((o) => o.is_undercut).length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const orderFiltersActive = orderSearch.trim() !== "" || orderRegion !== "all" || orderUndercutOnly;

  function clearOrderFilters() {
    setOrderSearch("");
    setOrderRegion("all");
    setOrderUndercutOnly(false);
    setOrderSort("name");
    setOrderSortDir("asc");
  }

  function filterAndSortOrders(orders: CharacterOrder[]): CharacterOrder[] {
    const q = orderSearch.trim().toLowerCase();
    const filtered = orders.filter((o) => {
      if (q && !o.name.toLowerCase().includes(q)) return false;
      if (orderRegion === "tracked" && o.region_id !== TRACKED_REGION_ID) return false;
      if (orderRegion === "other" && o.region_id === TRACKED_REGION_ID) return false;
      if (orderUndercutOnly && !o.is_undercut) return false;
      return true;
    });
    const dir = orderSortDir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (orderSort === "name") return a.name.localeCompare(b.name) * dir;
      if (orderSort === "price") return (a.price - b.price) * dir;
      return (a.price * a.volume_remain - b.price * b.volume_remain) * dir;
    });
  }

  const filteredOrders = filterAndSortOrders(characterOrders);
  const buyOrders = filteredOrders.filter((o) => o.is_buy_order);
  const sellOrders = filteredOrders.filter((o) => !o.is_buy_order);
  const filteredClosedOrders = orderSearch.trim()
    ? closedOrders.filter((o) => o.name.toLowerCase().includes(orderSearch.trim().toLowerCase()))
    : closedOrders;
  const filteredFills = orderSearch.trim()
    ? orderFills.filter((f) => f.name.toLowerCase().includes(orderSearch.trim().toLowerCase()))
    : orderFills;
  type HistoryEvent =
    | { kind: "closed"; ts: string; data: CharacterOrderClosed }
    | { kind: "fill"; ts: string; data: CharacterOrderFill };
  const historyEvents: HistoryEvent[] = [
    ...filteredClosedOrders.map((o): HistoryEvent => ({ kind: "closed", ts: o.closed_at, data: o })),
    ...filteredFills.map((f): HistoryEvent => ({ kind: "fill", ts: f.filled_at, data: f })),
  ].sort((a, b) => b.ts.localeCompare(a.ts));
  const orderValue = (orders: CharacterOrder[]) =>
    orders.reduce((sum, o) => sum + o.price * o.volume_remain, 0);

  function renderOrderRow(o: CharacterOrder) {
    return (
      <div key={o.order_id} className={o.is_undercut ? "order-card undercut" : "order-card"}>
        <div className="order-card-top">
          <span className="row-name">{o.name}</span>
          <button
            className="row-action"
            title="Abrir en cliente EVE"
            onClick={() => openInClient(o.type_id)}
          >
            ↗
          </button>
        </div>
        <div className="order-card-prices">
          <span className={o.is_undercut ? "order-price negative" : "order-price"}>{formatIskValue(o.price)}</span>
          <span className={o.is_undercut ? "order-mkt negative" : "order-mkt positive"}>
            {o.is_undercut
              ? `${o.orders_ahead} por delante · -${formatIskValue(o.price_gap)}`
              : "Vas primero"}
          </span>
        </div>
        <span className="row-sub">
          {o.is_undercut && "⚠ Undercuteada · "}
          {o.region_id !== TRACKED_REGION_ID && "Fuera de The Forge · "}
          {formatIsk(o.volume_remain)}/{formatIsk(o.volume_total)} u
        </span>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="bg-blob blob-a" />
      <div className="bg-blob blob-b" />

      <nav className="navbar">
        <div className="navbar-inner">
          <div className="navbar-brand">
            <span className="live-dot" />
            <span className="navbar-title">EveMarket</span>
          </div>
          <div className="navbar-meta">
            {authenticated && (
              <span>WALLET <b>{wallet != null ? formatIskValue(wallet) : "sin autorizar"}</b></span>
            )}
            <span>EVE {now.toISOString().slice(11, 19)} · Local {now.toLocaleTimeString()}</span>
            <span>Mercado (4h): <b>{formatCountdown(schedule?.market_next_run ?? null, now)}</b></span>
            <span>Posiciones (5min): <b>{formatCountdown(schedule?.positions_next_run ?? null, now)}</b></span>
          </div>
          <div className="navbar-links">
            <button
              className={view === "screener" ? "navbar-link active" : "navbar-link"}
              onClick={() => setView("screener")}
            >
              Screener
            </button>
            {authenticated && (
              <button
                className={view === "orders" ? "navbar-link active" : "navbar-link"}
                onClick={() => setView("orders")}
              >
                Mis Órdenes
                {undercutCount > 0 && <span className="badge badge-warning">{undercutCount}</span>}
              </button>
            )}
            {authenticated && (
              <button
                className={view === "settings" ? "navbar-link active" : "navbar-link"}
                onClick={() => setView("settings")}
              >
                Ajustes
              </button>
            )}
            {!authenticated && (
              <a className="navbar-link" href={api.authLoginUrl}>
                Iniciar sesión
              </a>
            )}
          </div>
        </div>
      </nav>

      {view === "orders" ? (
        <>
          {error && <p className="error">{error}</p>}
          {ordersLoading && <p className="muted">Cargando…</p>}

          <div className="section-title-row">
            <h3 className="section-title">Órdenes activas ({characterOrders.length})</h3>
            <button className="btn-refresh" onClick={refreshOrders} disabled={ordersRefreshing}>
              {ordersRefreshing ? "Refrescando…" : "Refrescar ↻"}
            </button>
          </div>

          <button className="filters-toggle glass-panel" onClick={() => setShowOrderFilters((s) => !s)}>
            {showOrderFilters ? "Ocultar filtros ▲" : "Filtros ▼"}
            {orderFiltersActive && <span className="badge">activos</span>}
          </button>

          {showOrderFilters && (
            <div className="glass-panel filters-panel">
              <label>
                Buscar por nombre
                <input
                  type="text"
                  placeholder="Ej. Charge, Compressed…"
                  value={orderSearch}
                  onChange={(e) => setOrderSearch(e.target.value)}
                />
              </label>

              <div className="sort-row">
                <label>
                  Ordenar por
                  <select value={orderSort} onChange={(e) => setOrderSort(e.target.value as "name" | "price" | "value")}>
                    <option value="name">Nombre</option>
                    <option value="price">Precio</option>
                    <option value="value">Valor total</option>
                  </select>
                </label>
                <div className="sort-order-toggle">
                  <button
                    className={orderSortDir === "asc" ? "btn-toggle active" : "btn-toggle"}
                    onClick={() => setOrderSortDir("asc")}
                  >
                    Ascendente ↑
                  </button>
                  <button
                    className={orderSortDir === "desc" ? "btn-toggle active" : "btn-toggle"}
                    onClick={() => setOrderSortDir("desc")}
                  >
                    Descendente ↓
                  </button>
                </div>
              </div>

              <label>
                Región
                <select value={orderRegion} onChange={(e) => setOrderRegion(e.target.value as "all" | "tracked" | "other")}>
                  <option value="all">Todas</option>
                  <option value="tracked">Solo The Forge</option>
                  <option value="other">Fuera de The Forge</option>
                </select>
              </label>

              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={orderUndercutOnly}
                  onChange={(e) => setOrderUndercutOnly(e.target.checked)}
                />
                Solo undercuteadas
              </label>

              <div className="filter-actions">
                <button className="btn-secondary" onClick={clearOrderFilters}>Limpiar</button>
              </div>
            </div>
          )}

          <div className="order-groups">
            <div className="order-group">
              <div className="section-title-row">
                <h4 className="section-subtitle">Compra ({buyOrders.length})</h4>
                <span className="section-value">{formatIskValue(orderValue(buyOrders))}</span>
              </div>
              <div className="glass-panel data-panel">
                {buyOrders.map(renderOrderRow)}
                {!ordersLoading && buyOrders.length === 0 && (
                  <p className="muted panel-empty">
                    {orderFiltersActive ? "Sin resultados con estos filtros." : "Sin órdenes de compra activas."}
                  </p>
                )}
              </div>
            </div>

            <div className="order-group">
              <div className="section-title-row">
                <h4 className="section-subtitle">Venta ({sellOrders.length})</h4>
                <span className="section-value">{formatIskValue(orderValue(sellOrders))}</span>
              </div>
              <div className="glass-panel data-panel">
                {sellOrders.map(renderOrderRow)}
                {!ordersLoading && sellOrders.length === 0 && (
                  <p className="muted panel-empty">
                    {orderFiltersActive ? "Sin resultados con estos filtros." : "Sin órdenes de venta activas."}
                  </p>
                )}
              </div>
            </div>
          </div>

          {!ordersLoading && characterOrders.length === 0 && (
            <p className="muted panel-empty">
              Sin órdenes activas, o todavía no autorizaste el scope de órdenes
              (correr scripts/authorize.py).
            </p>
          )}
          {openWindowMsg && <p className="muted">{openWindowMsg}</p>}

          <h3 className="section-title">Historial reciente</h3>
          <div className="glass-panel data-panel">
            <div className="data-row data-header">
              <span className="col-item">ITEM</span>
              <span className="col-num">PRECIO</span>
              <span className="col-num">ESTADO</span>
              <span className="col-action-spacer" />
            </div>
            {historyEvents.map((e) =>
              e.kind === "closed" ? (
                <div key={`closed-${e.data.order_id}-${e.data.closed_at}`} className="data-row">
                  <span className="col-item">
                    <span className="row-name">{e.data.name}</span>
                    <span className="row-sub">
                      {e.data.is_buy_order ? "Compra" : "Venta"} · {e.data.closed_at.slice(0, 16).replace("T", " ")}
                    </span>
                  </span>
                  <span className="col-num">{formatIskValue(e.data.price)}</span>
                  <span className="col-num muted-num">
                    {CLOSED_STATE_LABEL[e.data.final_state] ?? e.data.final_state}
                  </span>
                  <button
                    className="row-action"
                    title="Abrir en cliente EVE"
                    onClick={() => openInClient(e.data.type_id)}
                  >
                    ↗
                  </button>
                </div>
              ) : (
                <div key={`fill-${e.data.id}`} className="data-row">
                  <span className="col-item">
                    <span className="row-name">{e.data.name}</span>
                    <span className="row-sub">
                      {e.data.is_buy_order ? "Compra parcial" : "Venta parcial"} ·{" "}
                      {e.data.filled_at.slice(0, 16).replace("T", " ")}
                    </span>
                  </span>
                  <span className="col-num">{formatIskValue(e.data.price)}</span>
                  <span className="col-num muted-num">{formatIsk(e.data.filled_units)} u</span>
                  <button
                    className="row-action"
                    title="Abrir en cliente EVE"
                    onClick={() => openInClient(e.data.type_id)}
                  >
                    ↗
                  </button>
                </div>
              ),
            )}
            {!ordersLoading && historyEvents.length === 0 && (
              <p className="muted panel-empty">
                {orderSearch.trim() ? "Sin resultados con estos filtros." : "Sin cierres registrados todavía."}
              </p>
            )}
          </div>
        </>
      ) : view === "settings" ? (
        <>
          <h3 className="section-title">Ajustes</h3>
          <p className="muted">
            Todos los parámetros que usan los motores para el análisis y la clasificación. Un
            cambio se aplica en la próxima corrida de cada motor (mercado cada 4h, posiciones
            cada 5 min) — no es retroactivo.
          </p>

          {settingsLoading && <p className="muted">Cargando…</p>}

          {Object.entries(settingsByCategory).map(([category, rows]) => (
            <div key={category}>
              <h4 className="section-subtitle-standalone">{category}</h4>
              <div className="glass-panel filters-panel">
                {rows.map((s) => (
                  <label key={s.key}>
                    {s.label}
                    <input
                      type="number"
                      min={0}
                      step="any"
                      value={settingsForm[s.key] ?? ""}
                      onChange={(e) => setSettingsForm({ ...settingsForm, [s.key]: e.target.value })}
                    />
                    <span className="field-hint">{s.description}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}

          {settings.length > 0 && (
            <div className="glass-panel filters-panel">
              <div className="filter-actions">
                <button className="btn-primary" onClick={saveSettings} disabled={settingsSaving}>
                  {settingsSaving ? "Guardando…" : "Guardar cambios"}
                </button>
                <button className="btn-secondary" onClick={resetSettings} disabled={settingsResetting}>
                  {settingsResetting ? "Restableciendo…" : "Restablecer valores por defecto"}
                </button>
              </div>
              {settingsMsg && <p className="muted">{settingsMsg}</p>}
            </div>
          )}
        </>
      ) : (
      <>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={t.key === tab ? "tab active" : "tab"}
            onClick={() => { setTab(t.key); setPage(0); }}
          >
            {t.label}
            {summary && <span className="badge">{summary.counts[t.key] ?? 0}</span>}
          </button>
        ))}
      </nav>

      <button className="filters-toggle glass-panel" onClick={() => setShowFilters((s) => !s)}>
        {showFilters ? "Ocultar filtros ▲" : "Filtros ▼"}
        {Object.keys(appliedFilters).length > 0 && <span className="badge">activos</span>}
      </button>

      {showFilters && (
        <div className="glass-panel filters-panel">
          <div className="sort-row">
            <label>
              Ordenar por
              <select value={sortField} onChange={(e) => { setSortField(e.target.value); setPage(0); }}>
                {SORT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
            <div className="sort-order-toggle">
              <button
                className={sortOrder === "desc" ? "btn-toggle active" : "btn-toggle"}
                onClick={() => { setSortOrder("desc"); setPage(0); }}
              >
                Descendente ↓
              </button>
              <button
                className={sortOrder === "asc" ? "btn-toggle active" : "btn-toggle"}
                onClick={() => { setSortOrder("asc"); setPage(0); }}
              >
                Ascendente ↑
              </button>
            </div>
          </div>

          <label>
            Categoría
            <select
              value={filterForm.categoryId}
              onChange={(e) => setFilterForm({ ...filterForm, categoryId: e.target.value })}
            >
              <option value="">Todas</option>
              {categories.map((c) => (
                <option key={c.category_id} value={c.category_id}>{c.category_name}</option>
              ))}
            </select>
          </label>

          <div className="filter-range">
            <span>ROI %</span>
            <input type="number" placeholder="min" value={filterForm.minRoi}
              onChange={(e) => setFilterForm({ ...filterForm, minRoi: e.target.value })} />
            <input type="number" placeholder="max" value={filterForm.maxRoi}
              onChange={(e) => setFilterForm({ ...filterForm, maxRoi: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>Spread %</span>
            <input type="number" placeholder="min" value={filterForm.minSpread}
              onChange={(e) => setFilterForm({ ...filterForm, minSpread: e.target.value })} />
            <input type="number" placeholder="max" value={filterForm.maxSpread}
              onChange={(e) => setFilterForm({ ...filterForm, maxSpread: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>Precio compra (ISK)</span>
            <input type="number" placeholder="min" value={filterForm.minBuy}
              onChange={(e) => setFilterForm({ ...filterForm, minBuy: e.target.value })} />
            <input type="number" placeholder="max" value={filterForm.maxBuy}
              onChange={(e) => setFilterForm({ ...filterForm, maxBuy: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>Precio venta (ISK)</span>
            <input type="number" placeholder="min" value={filterForm.minSell}
              onChange={(e) => setFilterForm({ ...filterForm, minSell: e.target.value })} />
            <input type="number" placeholder="max" value={filterForm.maxSell}
              onChange={(e) => setFilterForm({ ...filterForm, maxSell: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>Volumen diario</span>
            <input type="number" placeholder="min" value={filterForm.minVolume}
              onChange={(e) => setFilterForm({ ...filterForm, minVolume: e.target.value })} />
            <input type="number" placeholder="max" value={filterForm.maxVolume}
              onChange={(e) => setFilterForm({ ...filterForm, maxVolume: e.target.value })} />
          </div>

          <div className="filter-actions">
            <button className="btn-primary" onClick={applyFilters}>Aplicar</button>
            <button className="btn-secondary" onClick={clearFilters}>Limpiar</button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Cargando…</p>}

      <div className="glass-panel data-panel">
        <div className="data-row data-header">
          <span className="col-item">ITEM</span>
          <span className="col-num">BUY</span>
          <span className="col-num">SELL</span>
          <span className="col-num">ROI</span>
        </div>
        {items.map((item) => (
          <div key={item.type_id} className="data-row clickable" onClick={() => openItem(item.type_id)}>
            <span className="col-item">
              <span className="row-name">{item.name}</span>
              <span className="row-sub">
                {item.category_name ?? "—"} · {item.evaluacion_spread}
              </span>
              <span className="row-sub">
                {item.avg_daily_order_count_7d.toFixed(1)} operaciones/día
              </span>
            </span>
            <span className="col-num">{formatIskValue(item.best_buy)}</span>
            <span className="col-num">{formatIskValue(item.best_sell)}</span>
            <span className={item.roi >= 0 ? "col-num positive" : "col-num negative"}>{formatPct(item.roi)}</span>
          </div>
        ))}
        {!loading && items.length === 0 && <p className="muted panel-empty">Sin ítems para este filtro todavía.</p>}
      </div>

      {total > 0 && (
        <div className="glass-panel pagination">
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>← Anterior</button>
          <span>Página {page + 1} de {totalPages} ({formatIsk(total)})</span>
          <button disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>Siguiente →</button>
        </div>
      )}
      </>
      )}

      {selected && (
        <div className="drawer" onClick={() => setSelected(null)}>
          <div className="glass-panel drawer-content" onClick={(e) => e.stopPropagation()}>
            <button className="close" onClick={() => setSelected(null)}>✕</button>
            <h2>{selected.status.name}</h2>
            <p className="muted">
              {selected.status.category_name ? `${selected.status.category_name} · ${selected.status.group_name}` : ""}
            </p>
            <p className="muted">{selected.status.reason}</p>

            {authenticated && (
              <button className="btn-secondary open-client-btn" onClick={() => openInClient(selected.status.type_id)}>
                Abrir en cliente EVE ↗
              </button>
            )}
            {openWindowMsg && <p className="muted">{openWindowMsg}</p>}

            {selected.latest_snapshot && (
              <div className="detail-grid">
                <div><span className="label">Best buy</span>{formatIskValue(selected.latest_snapshot.best_buy)}</div>
                <div><span className="label">Best sell</span>{formatIskValue(selected.latest_snapshot.best_sell)}</div>
                <div><span className="label">Órdenes activas (compra)</span>{formatIsk(selected.latest_snapshot.buy_order_count)}</div>
                <div><span className="label">Órdenes activas (venta)</span>{formatIsk(selected.latest_snapshot.sell_order_count)}</div>
                <div><span className="label">Volumen real 7d</span>{formatIsk(selected.status.avg_daily_volume_7d)} u/día</div>
                <div><span className="label">Operaciones 7d</span>{selected.status.avg_daily_order_count_7d.toFixed(1)}/día</div>
              </div>
            )}

            {(recommendation ?? selected.latest_opportunities[0]) && (
              <div className="recommendation">
                <strong>Recomendación:</strong>{" "}
                {(recommendation ?? selected.latest_opportunities[0]).recomendacion}
                {recommendation?.unidades_sugeridas != null && (
                  <>
                    {" "}
                    <span className="muted">
                      (sugerido ahora: {formatIsk(recommendation.unidades_sugeridas)} u)
                    </span>
                  </>
                )}
              </div>
            )}

            <h3>Histórico reciente</h3>
            <table className="history-table">
              <thead>
                <tr><th>Fecha</th><th>Avg</th><th>Vol</th></tr>
              </thead>
              <tbody>
                {selected.history.slice(0, 14).map((h) => (
                  <tr key={h.date}>
                    <td>{h.date}</td>
                    <td>{formatIskValue(h.avg_price)}</td>
                    <td>{formatIsk(h.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
