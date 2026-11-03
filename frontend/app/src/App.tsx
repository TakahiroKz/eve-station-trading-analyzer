import { useEffect, useState } from "react";
import {
  api, type AppSetting, type Category, type CharacterOrder, type CharacterOrderClosed,
  type CharacterOrderFill, type ItemDetail, type ItemFilters, type ItemStatus, type Opportunity,
  type Schedule, type Status, type Summary,
} from "./api";
import { DONATE_URL } from "./config";
import {
  LANGS, isLang, translateReason, translateRecommendation,
  translateSettingCategory, translateSettingLabel, translateSpread, type MessageKey, type TFunction,
} from "./i18n";
import { useI18n } from "./i18n/useI18n";
import "./App.css";

// The backend stores closed-order states in Spanish; these are the known values.
const CLOSED_STATES = ["completada", "expirada", "cancelada", "cerrada"];

const TAB_KEYS: Status[] = ["POTENCIAL", "POTENCIAL_SIN_ORDENES", "EN_OBSERVACION", "DESCARTADO"];

const PAGE_SIZE = 50;
const TRACKED_REGION_ID = 10000002; // The Forge / Jita

const SORT_VALUES = [
  "volumen_diario_real", "roi", "spread_bruto", "best_buy", "best_sell",
  "avg_daily_order_count_7d", "name",
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

function formatPct(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatCountdown(target: string | null, now: Date, t: TFunction): string {
  if (!target) return t("schedule.none");
  const diffMs = new Date(target).getTime() - now.getTime();
  if (diffMs <= 0) return t("schedule.running");
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
  const { t, lang, setLang, locale } = useI18n();

  const formatIsk = (value: number | null | undefined) => {
    if (value == null) return "—";
    // maximumFractionDigits: 2 porque el ISK no tiene más precisión que eso — cubre
    // sin redondear a cero los precios chicos (ítems de pocas ISK con decimales
    // significativos), sin agregar ".00" de más en los enteros (no hay minimum).
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
  };
  const formatIskValue = (value: number | null | undefined) =>
    value == null ? "—" : `${formatIsk(value)} ISK`;

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
  // "thanks" es la página de agradecimiento: PayPal redirige a `/?gracias=1` al terminar
  // una donación (se configura como return URL del botón Donar, ver OPERATIONS.md).
  const [view, setView] = useState<"screener" | "orders" | "settings" | "thanks">(() => {
    const params = new URLSearchParams(window.location.search);
    return params.has("gracias") || params.has("thanks") ? "thanks" : "screener";
  });
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
    if (!authenticated && view !== "screener" && view !== "thanks") setView("screener");
  }, [authenticated, view]);

  useEffect(() => {
    // Al salir de la página de agradecimiento, sacar `?gracias=1` de la URL para que
    // recargar no la vuelva a mostrar (se conserva `?lang=`).
    const params = new URLSearchParams(window.location.search);
    if (view !== "thanks" && (params.has("gracias") || params.has("thanks"))) {
      params.delete("gracias");
      params.delete("thanks");
      const rest = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : ""));
    }
  }, [view]);

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
      setSettingsMsg(t("settings.invalid"));
      return;
    }
    if (changed.length === 0) {
      setSettingsMsg(t("settings.noChanges"));
      return;
    }

    setSettingsSaving(true);
    setSettingsMsg(null);
    Promise.all(changed.map((s) => api.updateSetting(s.key, Number(settingsForm[s.key]))))
      .then(() => {
        setSettingsMsg(t(changed.length === 1 ? "settings.savedOne" : "settings.savedMany", { n: changed.length }));
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
        setSettingsMsg(t("settings.resetDone"));
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
    setOpenWindowMsg(t("common.opening"));
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
            title={t("common.openInClient")}
            onClick={() => openInClient(o.type_id)}
          >
            ↗
          </button>
        </div>
        <div className="order-card-prices">
          <span className={o.is_undercut ? "order-price negative" : "order-price"}>{formatIskValue(o.price)}</span>
          <span className={o.is_undercut ? "order-mkt negative" : "order-mkt positive"}>
            {o.is_undercut
              ? t("orders.ahead", { n: o.orders_ahead, gap: formatIskValue(o.price_gap) })
              : t("orders.first")}
          </span>
        </div>
        <span className="row-sub">
          {o.is_undercut && t("orders.undercutFlag")}
          {o.region_id !== TRACKED_REGION_ID && t("orders.outsideForge")}
          {formatIsk(o.volume_remain)}/{formatIsk(o.volume_total)} {t("common.units")}
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
              <span>{t("nav.wallet")} <b>{wallet != null ? formatIskValue(wallet) : t("nav.notAuthorized")}</b></span>
            )}
            <span>EVE {now.toISOString().slice(11, 19)} · {t("nav.local")} {now.toLocaleTimeString(locale)}</span>
            <span>{t("nav.market")}: <b>{formatCountdown(schedule?.market_next_run ?? null, now, t)}</b></span>
            <span>{t("nav.positions")}: <b>{formatCountdown(schedule?.positions_next_run ?? null, now, t)}</b></span>
          </div>
          <div className="navbar-links">
            <select
              className="navbar-link lang-select"
              aria-label={t("nav.language")}
              value={lang}
              onChange={(e) => { if (isLang(e.target.value)) setLang(e.target.value); }}
            >
              {LANGS.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
            <button
              className={view === "screener" ? "navbar-link active" : "navbar-link"}
              onClick={() => setView("screener")}
            >
              {t("nav.screener")}
            </button>
            {authenticated && (
              <button
                className={view === "orders" ? "navbar-link active" : "navbar-link"}
                onClick={() => setView("orders")}
              >
                {t("nav.orders")}
                {undercutCount > 0 && <span className="badge badge-warning">{undercutCount}</span>}
              </button>
            )}
            {authenticated && (
              <button
                className={view === "settings" ? "navbar-link active" : "navbar-link"}
                onClick={() => setView("settings")}
              >
                {t("nav.settings")}
              </button>
            )}
            {!authenticated && (
              <a className="navbar-link" href={api.authLoginUrl}>
                {t("nav.login")}
              </a>
            )}
            {DONATE_URL && (
              <a className="navbar-link navbar-donate" href={DONATE_URL} target="_blank" rel="noopener noreferrer">
                {t("nav.donate")}
              </a>
            )}
          </div>
        </div>
      </nav>

      {view === "thanks" ? (
        <div className="glass-panel thanks-panel">
          <div className="thanks-heart">♥</div>
          <h2>{t("thanks.title")}</h2>
          <p>{t("thanks.body")}</p>
          <button className="btn-primary" onClick={() => setView("screener")}>
            {t("thanks.back")}
          </button>
        </div>
      ) : view === "orders" ? (
        <>
          {error && <p className="error">{error}</p>}
          {ordersLoading && <p className="muted">{t("common.loading")}</p>}

          <div className="section-title-row">
            <h3 className="section-title">{t("orders.active", { n: characterOrders.length })}</h3>
            <button className="btn-refresh" onClick={refreshOrders} disabled={ordersRefreshing}>
              {ordersRefreshing ? t("orders.refreshing") : t("orders.refresh")}
            </button>
          </div>

          <button className="filters-toggle glass-panel" onClick={() => setShowOrderFilters((s) => !s)}>
            {showOrderFilters ? t("filters.hide") : t("filters.show")}
            {orderFiltersActive && <span className="badge">{t("filters.active")}</span>}
          </button>

          {showOrderFilters && (
            <div className="glass-panel filters-panel">
              <label>
                {t("orders.searchByName")}
                <input
                  type="text"
                  placeholder={t("orders.searchPlaceholder")}
                  value={orderSearch}
                  onChange={(e) => setOrderSearch(e.target.value)}
                />
              </label>

              <div className="sort-row">
                <label>
                  {t("common.sortBy")}
                  <select value={orderSort} onChange={(e) => setOrderSort(e.target.value as "name" | "price" | "value")}>
                    <option value="name">{t("orders.sortName")}</option>
                    <option value="price">{t("orders.sortPrice")}</option>
                    <option value="value">{t("orders.sortValue")}</option>
                  </select>
                </label>
                <div className="sort-order-toggle">
                  <button
                    className={orderSortDir === "asc" ? "btn-toggle active" : "btn-toggle"}
                    onClick={() => setOrderSortDir("asc")}
                  >
                    {t("common.ascending")}
                  </button>
                  <button
                    className={orderSortDir === "desc" ? "btn-toggle active" : "btn-toggle"}
                    onClick={() => setOrderSortDir("desc")}
                  >
                    {t("common.descending")}
                  </button>
                </div>
              </div>

              <label>
                {t("orders.region")}
                <select value={orderRegion} onChange={(e) => setOrderRegion(e.target.value as "all" | "tracked" | "other")}>
                  <option value="all">{t("orders.regionAll")}</option>
                  <option value="tracked">{t("orders.regionTracked")}</option>
                  <option value="other">{t("orders.regionOther")}</option>
                </select>
              </label>

              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={orderUndercutOnly}
                  onChange={(e) => setOrderUndercutOnly(e.target.checked)}
                />
                {t("orders.undercutOnly")}
              </label>

              <div className="filter-actions">
                <button className="btn-secondary" onClick={clearOrderFilters}>{t("common.clear")}</button>
              </div>
            </div>
          )}

          <div className="order-groups">
            <div className="order-group">
              <div className="section-title-row">
                <h4 className="section-subtitle">{t("orders.buy", { n: buyOrders.length })}</h4>
                <span className="section-value">{formatIskValue(orderValue(buyOrders))}</span>
              </div>
              <div className="glass-panel data-panel">
                {buyOrders.map(renderOrderRow)}
                {!ordersLoading && buyOrders.length === 0 && (
                  <p className="muted panel-empty">
                    {orderFiltersActive ? t("filters.noResults") : t("orders.noBuy")}
                  </p>
                )}
              </div>
            </div>

            <div className="order-group">
              <div className="section-title-row">
                <h4 className="section-subtitle">{t("orders.sell", { n: sellOrders.length })}</h4>
                <span className="section-value">{formatIskValue(orderValue(sellOrders))}</span>
              </div>
              <div className="glass-panel data-panel">
                {sellOrders.map(renderOrderRow)}
                {!ordersLoading && sellOrders.length === 0 && (
                  <p className="muted panel-empty">
                    {orderFiltersActive ? t("filters.noResults") : t("orders.noSell")}
                  </p>
                )}
              </div>
            </div>
          </div>

          {!ordersLoading && characterOrders.length === 0 && (
            <p className="muted panel-empty">{t("orders.noneOrNotAuthorized")}</p>
          )}
          {openWindowMsg && <p className="muted">{openWindowMsg}</p>}

          <h3 className="section-title">{t("orders.history")}</h3>
          <div className="glass-panel data-panel">
            <div className="data-row data-header">
              <span className="col-item">{t("orders.colItem")}</span>
              <span className="col-num">{t("orders.colPrice")}</span>
              <span className="col-num">{t("orders.colStatus")}</span>
              <span className="col-action-spacer" />
            </div>
            {historyEvents.map((e) =>
              e.kind === "closed" ? (
                <div key={`closed-${e.data.order_id}-${e.data.closed_at}`} className="data-row">
                  <span className="col-item">
                    <span className="row-name">{e.data.name}</span>
                    <span className="row-sub">
                      {e.data.is_buy_order ? t("orders.kindBuy") : t("orders.kindSell")} · {e.data.closed_at.slice(0, 16).replace("T", " ")}
                    </span>
                  </span>
                  <span className="col-num">{formatIskValue(e.data.price)}</span>
                  <span className="col-num muted-num">
                    {CLOSED_STATES.includes(e.data.final_state)
                      ? t(`closed.${e.data.final_state}` as MessageKey)
                      : e.data.final_state}
                  </span>
                  <button
                    className="row-action"
                    title={t("common.openInClient")}
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
                      {e.data.is_buy_order ? t("orders.kindPartialBuy") : t("orders.kindPartialSell")} ·{" "}
                      {e.data.filled_at.slice(0, 16).replace("T", " ")}
                    </span>
                  </span>
                  <span className="col-num">{formatIskValue(e.data.price)}</span>
                  <span className="col-num muted-num">{formatIsk(e.data.filled_units)} {t("common.units")}</span>
                  <button
                    className="row-action"
                    title={t("common.openInClient")}
                    onClick={() => openInClient(e.data.type_id)}
                  >
                    ↗
                  </button>
                </div>
              ),
            )}
            {!ordersLoading && historyEvents.length === 0 && (
              <p className="muted panel-empty">
                {orderSearch.trim() ? t("filters.noResults") : t("orders.historyEmpty")}
              </p>
            )}
          </div>
        </>
      ) : view === "settings" ? (
        <>
          <h3 className="section-title">{t("settings.title")}</h3>
          <p className="muted">{t("settings.intro")}</p>

          {settingsLoading && <p className="muted">{t("common.loading")}</p>}

          {Object.entries(settingsByCategory).map(([category, rows]) => (
            <div key={category}>
              <h4 className="section-subtitle-standalone">{translateSettingCategory(t, category)}</h4>
              <div className="glass-panel filters-panel">
                {rows.map((s) => (
                  <label key={s.key}>
                    {translateSettingLabel(t, s.key, s.label)}
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
                  {settingsSaving ? t("settings.saving") : t("settings.save")}
                </button>
                <button className="btn-secondary" onClick={resetSettings} disabled={settingsResetting}>
                  {settingsResetting ? t("settings.resetting") : t("settings.reset")}
                </button>
              </div>
              {settingsMsg && <p className="muted">{settingsMsg}</p>}
            </div>
          )}
        </>
      ) : (
      <>
      <nav className="tabs">
        {TAB_KEYS.map((key) => (
          <button
            key={key}
            className={key === tab ? "tab active" : "tab"}
            onClick={() => { setTab(key); setPage(0); }}
          >
            {t(`tab.${key}` as MessageKey)}
            {summary && <span className="badge">{summary.counts[key] ?? 0}</span>}
          </button>
        ))}
      </nav>

      <button className="filters-toggle glass-panel" onClick={() => setShowFilters((s) => !s)}>
        {showFilters ? t("filters.hide") : t("filters.show")}
        {Object.keys(appliedFilters).length > 0 && <span className="badge">{t("filters.active")}</span>}
      </button>

      {showFilters && (
        <div className="glass-panel filters-panel">
          <div className="sort-row">
            <label>
              {t("common.sortBy")}
              <select value={sortField} onChange={(e) => { setSortField(e.target.value); setPage(0); }}>
                {SORT_VALUES.map((value) => (
                  <option key={value} value={value}>{t(`sort.${value}` as MessageKey)}</option>
                ))}
              </select>
            </label>
            <div className="sort-order-toggle">
              <button
                className={sortOrder === "desc" ? "btn-toggle active" : "btn-toggle"}
                onClick={() => { setSortOrder("desc"); setPage(0); }}
              >
                {t("common.descending")}
              </button>
              <button
                className={sortOrder === "asc" ? "btn-toggle active" : "btn-toggle"}
                onClick={() => { setSortOrder("asc"); setPage(0); }}
              >
                {t("common.ascending")}
              </button>
            </div>
          </div>

          <label>
            {t("filters.category")}
            <select
              value={filterForm.categoryId}
              onChange={(e) => setFilterForm({ ...filterForm, categoryId: e.target.value })}
            >
              <option value="">{t("common.all")}</option>
              {categories.map((c) => (
                <option key={c.category_id} value={c.category_id}>{c.category_name}</option>
              ))}
            </select>
          </label>

          <div className="filter-range">
            <span>{t("filters.roi")}</span>
            <input type="number" placeholder={t("common.min")} value={filterForm.minRoi}
              onChange={(e) => setFilterForm({ ...filterForm, minRoi: e.target.value })} />
            <input type="number" placeholder={t("common.max")} value={filterForm.maxRoi}
              onChange={(e) => setFilterForm({ ...filterForm, maxRoi: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>{t("filters.spread")}</span>
            <input type="number" placeholder={t("common.min")} value={filterForm.minSpread}
              onChange={(e) => setFilterForm({ ...filterForm, minSpread: e.target.value })} />
            <input type="number" placeholder={t("common.max")} value={filterForm.maxSpread}
              onChange={(e) => setFilterForm({ ...filterForm, maxSpread: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>{t("filters.buyPrice")}</span>
            <input type="number" placeholder={t("common.min")} value={filterForm.minBuy}
              onChange={(e) => setFilterForm({ ...filterForm, minBuy: e.target.value })} />
            <input type="number" placeholder={t("common.max")} value={filterForm.maxBuy}
              onChange={(e) => setFilterForm({ ...filterForm, maxBuy: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>{t("filters.sellPrice")}</span>
            <input type="number" placeholder={t("common.min")} value={filterForm.minSell}
              onChange={(e) => setFilterForm({ ...filterForm, minSell: e.target.value })} />
            <input type="number" placeholder={t("common.max")} value={filterForm.maxSell}
              onChange={(e) => setFilterForm({ ...filterForm, maxSell: e.target.value })} />
          </div>

          <div className="filter-range">
            <span>{t("filters.dailyVolume")}</span>
            <input type="number" placeholder={t("common.min")} value={filterForm.minVolume}
              onChange={(e) => setFilterForm({ ...filterForm, minVolume: e.target.value })} />
            <input type="number" placeholder={t("common.max")} value={filterForm.maxVolume}
              onChange={(e) => setFilterForm({ ...filterForm, maxVolume: e.target.value })} />
          </div>

          <div className="filter-actions">
            <button className="btn-primary" onClick={applyFilters}>{t("common.apply")}</button>
            <button className="btn-secondary" onClick={clearFilters}>{t("common.clear")}</button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">{t("common.loading")}</p>}

      <div className="glass-panel data-panel">
        <div className="data-row data-header">
          <span className="col-item">{t("screener.colItem")}</span>
          <span className="col-num">{t("screener.colBuy")}</span>
          <span className="col-num">{t("screener.colSell")}</span>
          <span className="col-num">{t("screener.colRoi")}</span>
        </div>
        {items.map((item) => (
          <div key={item.type_id} className="data-row clickable" onClick={() => openItem(item.type_id)}>
            <span className="col-item">
              <span className="row-name">{item.name}</span>
              <span className="row-sub">
                {item.category_name ?? "—"} · {translateSpread(t, item.evaluacion_spread)}
              </span>
              <span className="row-sub">
                {t("screener.tradesPerDay", { n: item.avg_daily_order_count_7d.toFixed(1) })}
              </span>
            </span>
            <span className="col-num">{formatIskValue(item.best_buy)}</span>
            <span className="col-num">{formatIskValue(item.best_sell)}</span>
            <span className={item.roi >= 0 ? "col-num positive" : "col-num negative"}>{formatPct(item.roi)}</span>
          </div>
        ))}
        {!loading && items.length === 0 && <p className="muted panel-empty">{t("screener.empty")}</p>}
      </div>

      {total > 0 && (
        <div className="glass-panel pagination">
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>{t("screener.prev")}</button>
          <span>{t("screener.page", { page: page + 1, total: totalPages, count: formatIsk(total) })}</span>
          <button disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>{t("screener.next")}</button>
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
            <p className="muted">{translateReason(t, selected.status.reason)}</p>

            {authenticated && (
              <button className="btn-secondary open-client-btn" onClick={() => openInClient(selected.status.type_id)}>
                {t("common.openInClientButton")}
              </button>
            )}
            {openWindowMsg && <p className="muted">{openWindowMsg}</p>}

            {selected.latest_snapshot && (
              <div className="detail-grid">
                <div><span className="label">{t("detail.bestBuy")}</span>{formatIskValue(selected.latest_snapshot.best_buy)}</div>
                <div><span className="label">{t("detail.bestSell")}</span>{formatIskValue(selected.latest_snapshot.best_sell)}</div>
                <div><span className="label">{t("detail.activeBuyOrders")}</span>{formatIsk(selected.latest_snapshot.buy_order_count)}</div>
                <div><span className="label">{t("detail.activeSellOrders")}</span>{formatIsk(selected.latest_snapshot.sell_order_count)}</div>
                <div><span className="label">{t("detail.realVolume7d")}</span>{formatIsk(selected.status.avg_daily_volume_7d)} {t("detail.unitsPerDay")}</div>
                <div><span className="label">{t("detail.trades7d")}</span>{selected.status.avg_daily_order_count_7d.toFixed(1)}{t("detail.perDay")}</div>
              </div>
            )}

            {(recommendation ?? selected.latest_opportunities[0]) && (
              <div className="recommendation">
                <strong>{t("detail.recommendation")}</strong>{" "}
                {translateRecommendation(t, (recommendation ?? selected.latest_opportunities[0]).recomendacion, locale)}
                {recommendation?.unidades_sugeridas != null && (
                  <>
                    {" "}
                    <span className="muted">
                      {t("detail.suggestedNow", { n: formatIsk(recommendation.unidades_sugeridas) })}
                    </span>
                  </>
                )}
              </div>
            )}

            <h3>{t("detail.history")}</h3>
            <table className="history-table">
              <thead>
                <tr><th>{t("detail.colDate")}</th><th>{t("detail.colAvg")}</th><th>{t("detail.colVol")}</th></tr>
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

      {DONATE_URL && (
        <footer className="site-footer">
          <span>{t("footer.text")}</span>
          <a className="btn-donate" href={DONATE_URL} target="_blank" rel="noopener noreferrer">
            {t("footer.donate")}
          </a>
        </footer>
      )}
    </div>
  );
}
