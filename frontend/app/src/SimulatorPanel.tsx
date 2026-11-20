// Trade simulator: fees, taxes, profit and ROI of one trade with the player's own skills and standings (or a default /
// custom profile for visitors). All maths happens on the server (finance engine); this file only collects inputs and shows
// the breakdown, the order-book snapshot used and the saved scenarios.
import { useEffect, useState } from "react";
import type { MessageKey, TFunction } from "./i18n";

const MARKETS = [["jita", "Jita"], ["amarr", "Amarr"], ["dodixie", "Dodixie"], ["rens", "Rens"], ["hek", "Hek"]] as const;
type Mode = "LIMIT" | "IMMEDIATE";
type ProfileMode = "default" | "mine" | "manual";

interface Assessment {
  calculation_status: string;
  warnings: string[];
  rates: { broker_fee: string | null; sales_tax: string };
  result: Record<string, string> | null;
  targets: { break_even_sell_price?: string; target_sell_price?: string };
  capital: { available?: string; needed?: string; affordable?: boolean; max_units?: number };
}
interface Evaluation {
  assessment: Assessment;
  station: string;
  profile: { mode: string; source: string };
  book: { station: string; fetched_at: string; ask_levels: number; bid_levels: number } | null;
}
interface Scenario { id: number; name: string; created_at: string; request: Record<string, unknown>; result: Assessment }
interface ItemHit { type_id: number; name: string; best_buy: number; best_sell: number }
interface Form {
  market: string; units: string; buyMode: Mode; buyPrice: string; sellMode: Mode; sellPrice: string;
  venue: "NPC" | "UPWELL"; ownerFee: string; profileMode: ProfileMode; br: string; abr: string; acc: string; fs: string; cs: string;
  targetRoi: string; capital: string; useWallet: boolean;
}

const EMPTY: Form = {
  market: "jita", units: "100", buyMode: "LIMIT", buyPrice: "", sellMode: "LIMIT", sellPrice: "", venue: "NPC", ownerFee: "",
  profileMode: "default", br: "2", abr: "0", acc: "0", fs: "0", cs: "0", targetRoi: "0", capital: "", useWallet: false,
};
const MONEY = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function num(text: string): number | null {
  const n = Number(text.replace(",", "."));
  return text.trim() !== "" && Number.isFinite(n) ? n : null;
}
const pct = (ratio: string | null | undefined) => (ratio == null ? "—" : `${MONEY.format(Number(ratio) * 100)}%`);
const isk = (value: string | undefined) => (value == null ? "—" : `${MONEY.format(Number(value))} ISK`);

function warningText(t: TFunction, code: string): string {
  const [kind, a, b] = code.split(":");
  if (kind === "UNVERIFIED_RULE") return t("sim.warn.unverified", { rule: a });
  if (kind === "LOSS") return t("sim.warn.loss");
  if (kind === "PARTIAL_FILL") return t("sim.warn.partial", { side: a === "asks" ? t("sim.buy") : t("sim.sell"), fill: b });
  if (kind === "NO_LIQUIDITY") return t("sim.warn.noLiquidity", { side: a === "asks" ? t("sim.buy") : t("sim.sell") });
  if (kind === "MISSING") return t(a === "owner_fee_pct" ? "sim.warn.missingOwner" : "sim.warn.missingPrice");
  if (kind === "WALLET_UNAVAILABLE") return t("sim.warn.wallet");
  return code;
}

function buildRequest(form: Form, item: ItemHit | null): Record<string, unknown> | null {
  const units = num(form.units);
  if (units === null || !Number.isInteger(units) || units < 1) return null;
  const req: Record<string, unknown> = {
    market_id: form.market, units, buy_mode: form.buyMode, sell_mode: form.sellMode, venue: form.venue,
    profile_mode: form.profileMode, use_wallet: form.profileMode === "mine" && form.useWallet,
  };
  if (item) req.type_id = item.type_id;
  if (form.buyMode === "LIMIT") { const p = num(form.buyPrice); if (p === null) return null; req.buy_price = String(p); }
  if (form.sellMode === "LIMIT") { const p = num(form.sellPrice); if (p === null) return null; req.sell_price = String(p); }
  if ((form.buyMode === "IMMEDIATE" || form.sellMode === "IMMEDIATE")) {
    if (!item || form.venue !== "NPC") return null;
    req.use_live_book = true;
  }
  if (form.venue === "UPWELL") { const f = num(form.ownerFee); if (f !== null) req.owner_fee_percent = f; }
  const roi = num(form.targetRoi);
  if (roi !== null) req.target_roi_percent = roi;
  const cap = num(form.capital);
  if (cap !== null) req.available_capital = String(cap);
  if (form.profileMode === "manual") {
    req.manual_profile = {
      broker_relations: Number(form.br), advanced_broker_relations: Number(form.abr), accounting: Number(form.acc),
      faction_standing: num(form.fs) ?? 0, corp_standing: num(form.cs) ?? 0,
    };
  }
  return req;
}

export function SimulatorPanel({ t, onClose }: { t: TFunction; onClose: () => void }) {
  const [form, setForm] = useState<Form>(EMPTY);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ItemHit[]>([]);
  const [item, setItem] = useState<ItemHit | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<MessageKey | null>(null);
  const [out, setOut] = useState<Evaluation | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [picked, setPicked] = useState<number[]>([]);
  const [name, setName] = useState("");
  const [note, setNote] = useState<MessageKey | null>(null);
  const [compare, setCompare] = useState<{ name: string; assessment: Assessment }[] | null>(null);
  const [ranking, setRanking] = useState<string[]>([]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    void (async () => {
      try {
        const status = await (await fetch("/api/auth/status", { cache: "no-store" })).json() as { authenticated: boolean; needs_consent?: boolean };
        const ok = status.authenticated && !status.needs_consent;
        setSignedIn(ok);
        if (ok) {
          const r = await fetch("/api/me/scenarios", { cache: "no-store" });
          if (r.ok) setScenarios(((await r.json()) as { scenarios: Scenario[] }).scenarios);
        }
      } catch { /* the simulator works without an account */ }
    })();
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    const timer = window.setTimeout(() => {
      void fetch(`/api/items?q=${encodeURIComponent(q)}&market=${form.market}&limit=6`, { cache: "no-store" })
        .then(async (r) => (r.ok ? ((await r.json()) as { items: ItemHit[] }).items : []))
        .then(setHits).catch(() => setHits([]));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, form.market]);

  function pick(hit: ItemHit) {
    setItem(hit); setHits([]); setQuery("");
    setForm((f) => ({ ...f, buyPrice: String(hit.best_buy), sellPrice: String(hit.best_sell) }));
  }

  async function post(url: string, body: unknown): Promise<Response | null> {
    try {
      return await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch { return null; }
  }

  async function calculate() {
    setNote(null); setError(null); setCompare(null);
    const req = buildRequest(form, item);
    if (!req) { setError((form.buyMode === "IMMEDIATE" || form.sellMode === "IMMEDIATE") && !item ? "sim.needItem" : "sim.invalid"); return; }
    setBusy(true);
    const r = await post("/api/finance/evaluate", req);
    setBusy(false);
    if (!r || !r.ok) { setOut(null); setError(r?.status === 503 ? "sim.bookDown" : "sim.error"); return; }
    setOut((await r.json()) as Evaluation);
  }

  async function reloadScenarios() {
    const r = await fetch("/api/me/scenarios", { cache: "no-store" });
    if (r.ok) setScenarios(((await r.json()) as { scenarios: Scenario[] }).scenarios);
  }

  async function save() {
    const req = buildRequest(form, item);
    if (!req || !name.trim()) { setError("sim.invalid"); return; }
    setBusy(true);
    const r = await post("/api/me/scenarios", { name: name.trim(), request: req });
    setBusy(false);
    if (r?.status === 409) { setNote("sim.full"); return; }
    if (!r || !r.ok) { setError("sim.error"); return; }
    setName(""); setNote("sim.saved"); await reloadScenarios();
  }

  async function remove(id: number) {
    await fetch(`/api/me/scenarios/${id}`, { method: "DELETE" });
    setPicked((p) => p.filter((x) => x !== id));
    await reloadScenarios();
  }

  async function runCompare() {
    const chosen = scenarios.filter((s) => picked.includes(s.id));
    setBusy(true);
    const r = await post("/api/finance/compare", { scenarios: chosen.map((s) => ({ name: s.name, request: s.request })) });
    setBusy(false);
    if (!r || !r.ok) { setError("sim.error"); return; }
    const data = (await r.json()) as { results: { name: string; assessment: Assessment }[]; ranking: string[] };
    setCompare(data.results); setRanking(data.ranking);
  }

  const res = out?.assessment.result ?? null;
  const rows: [MessageKey, string][] = res ? [
    ["sim.r.buyCost", isk(res.buy_cost)], ["sim.r.buyFee", isk(res.buy_fee)], ["sim.r.sellGross", isk(res.sell_gross)],
    ["sim.r.sellFee", isk(res.sell_fee)], ["sim.r.salesTax", isk(res.sales_tax)], ["sim.r.relistFees", isk(res.relist_fees)],
    ["sim.r.totalCosts", isk(res.total_costs)], ["sim.r.capitalOutlay", isk(res.capital_outlay)],
  ] : [];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal sim-modal" role="dialog" aria-modal="true" aria-labelledby="sim-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="sim-title">{t("sim.title")}</h2>
        <p>{t("sim.intro")}</p>

        <div className="sim-grid">
          <label>{t("sim.market")}
            <select value={form.market} onChange={(e) => { set("market", e.target.value); setItem(null); }}>
              {MARKETS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label className="sim-wide">{t("sim.item")}
            <input value={query} placeholder={t("sim.itemSearch")} onChange={(e) => setQuery(e.target.value)} />
            {query.trim().length >= 2 && hits.length > 0 && (
              <ul className="sim-hits">
                {hits.map((h) => <li key={h.type_id}><button type="button" onClick={() => pick(h)}>{h.name}</button></li>)}
              </ul>
            )}
          </label>
        </div>
        <p className="profile-meta">
          {item ? t("sim.itemPick", { name: item.name, buy: MONEY.format(item.best_buy), sell: MONEY.format(item.best_sell) }) : t("sim.itemNone")}
        </p>

        <div className="sim-grid">
          <label>{t("sim.units")}<input inputMode="numeric" value={form.units} onChange={(e) => set("units", e.target.value)} /></label>
          <label>{t("sim.buy")}
            <select value={form.buyMode} onChange={(e) => set("buyMode", e.target.value as Mode)}>
              <option value="LIMIT">{t("sim.mode.LIMIT")}</option><option value="IMMEDIATE">{t("sim.mode.IMMEDIATE")}</option>
            </select>
          </label>
          <label>{t("sim.price")}
            <input inputMode="decimal" disabled={form.buyMode === "IMMEDIATE"} value={form.buyMode === "IMMEDIATE" ? "" : form.buyPrice}
              onChange={(e) => set("buyPrice", e.target.value)} />
          </label>
          <label>{t("sim.sell")}
            <select value={form.sellMode} onChange={(e) => set("sellMode", e.target.value as Mode)}>
              <option value="LIMIT">{t("sim.mode.LIMIT")}</option><option value="IMMEDIATE">{t("sim.mode.IMMEDIATE")}</option>
            </select>
          </label>
          <label>{t("sim.price")}
            <input inputMode="decimal" disabled={form.sellMode === "IMMEDIATE"} value={form.sellMode === "IMMEDIATE" ? "" : form.sellPrice}
              onChange={(e) => set("sellPrice", e.target.value)} />
          </label>
          <label>{t("sim.venue")}
            <select value={form.venue} onChange={(e) => set("venue", e.target.value as "NPC" | "UPWELL")}>
              <option value="NPC">{t("sim.venue.NPC")}</option><option value="UPWELL">{t("sim.venue.UPWELL")}</option>
            </select>
          </label>
          {form.venue === "UPWELL" && (
            <label>{t("sim.ownerFee")}<input inputMode="decimal" value={form.ownerFee} onChange={(e) => set("ownerFee", e.target.value)} /></label>
          )}
          <label>{t("sim.targetRoi")}<input inputMode="decimal" value={form.targetRoi} onChange={(e) => set("targetRoi", e.target.value)} /></label>
          <label>{t("sim.capital")}<input inputMode="decimal" value={form.capital} onChange={(e) => set("capital", e.target.value)} /></label>
        </div>

        <div className="sim-grid">
          <label>{t("sim.profile")}
            <select value={form.profileMode} onChange={(e) => set("profileMode", e.target.value as ProfileMode)}>
              <option value="default">{t("sim.profile.default")}</option>
              {signedIn && <option value="mine">{t("sim.profile.mine")}</option>}
              <option value="manual">{t("sim.profile.manual")}</option>
            </select>
          </label>
          {form.profileMode === "mine" && (
            <label className="sim-check"><input type="checkbox" checked={form.useWallet} onChange={(e) => set("useWallet", e.target.checked)} />
              {t("sim.useWallet")}</label>
          )}
          {form.profileMode === "manual" && (
            <>
              {([["br", "profile.skill.broker_relations"], ["abr", "profile.skill.advanced_broker_relations"], ["acc", "profile.skill.accounting"]] as const).map(([key, label]) => (
                <label key={key}>{t(label)}
                  <select value={form[key]} onChange={(e) => set(key, e.target.value)}>
                    {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                  </select>
                </label>
              ))}
              <label>{t("profile.col.factionStanding")}<input inputMode="decimal" value={form.fs} onChange={(e) => set("fs", e.target.value)} /></label>
              <label>{t("profile.col.corpStanding")}<input inputMode="decimal" value={form.cs} onChange={(e) => set("cs", e.target.value)} /></label>
            </>
          )}
        </div>

        {error && <p className="profile-warn" role="alert">{t(error)}</p>}
        <div className="modal-actions">
          <button className="account-btn" onClick={onClose}>{t("profile.close")}</button>
          <button className="account-btn primary" disabled={busy} onClick={() => void calculate()}>
            {busy ? t("sim.calculating") : t("sim.calculate")}
          </button>
        </div>

        {out && (
          <section className="sim-result" aria-live="polite">
            <h3>{t("sim.result")}</h3>
            {out.assessment.calculation_status !== "VALID" && <p className="profile-warn" role="alert">{t("sim.incomplete")}</p>}
            {out.assessment.warnings.map((w) => (
              <p key={w} className={w === "LOSS" ? "profile-warn" : "profile-meta"}>{warningText(t, w)}</p>
            ))}
            {res && (
              <>
                <p className={Number(res.net_profit) >= 0 ? "sim-big sim-gain" : "sim-big sim-loss"}>
                  {t("sim.r.netProfit")}: {isk(res.net_profit)} · {t("sim.r.roi")}: {pct(res.roi)} · {t("sim.r.margin")}: {pct(res.margin)}
                </p>
                <div className="profile-table-wrap">
                  <table className="profile-table"><tbody>
                    {rows.map(([key, value]) => <tr key={key}><th>{t(key)}</th><td>{value}</td></tr>)}
                    <tr><th>{t("sim.r.breakEven")}</th><td>{isk(out.assessment.targets.break_even_sell_price)}</td></tr>
                    <tr><th>{t("sim.r.targetSell")}</th><td>{isk(out.assessment.targets.target_sell_price)}</td></tr>
                  </tbody></table>
                </div>
                {out.assessment.capital.available != null && (
                  <p className="profile-meta">
                    {out.assessment.capital.affordable
                      ? t("sim.r.affordable") : t("sim.r.notAffordable", { n: out.assessment.capital.max_units ?? 0 })}
                  </p>
                )}
              </>
            )}
            <p className="profile-meta">
              {t("sim.r.rates", { broker: pct(out.assessment.rates.broker_fee), tax: pct(out.assessment.rates.sales_tax) })}
              {" · "}{t("sim.r.profile", { source: out.profile.source })}
            </p>
            {out.book && (
              <p className="profile-meta">{t("sim.r.book", { station: out.book.station, when: new Date(out.book.fetched_at).toLocaleTimeString() })}</p>
            )}
            {signedIn && (
              <div className="sim-save">
                <input value={name} maxLength={60} placeholder={t("sim.scenarioName")} onChange={(e) => setName(e.target.value)} />
                <button className="account-btn" disabled={busy || !name.trim()} onClick={() => void save()}>{t("sim.save")}</button>
              </div>
            )}
            {note && <p className="profile-ok" role="status">{t(note)}</p>}
          </section>
        )}

        {signedIn && (
          <section className="sim-scenarios">
            <h3>{t("sim.scenarios")}</h3>
            {scenarios.length === 0 ? <p className="profile-meta">{t("sim.scenarioNone")}</p> : (
              <ul className="sim-list">
                {scenarios.map((s) => (
                  <li key={s.id}>
                    <label>
                      <input type="checkbox" checked={picked.includes(s.id)}
                        onChange={(e) => setPicked((p) => (e.target.checked ? [...p, s.id] : p.filter((x) => x !== s.id)))} />
                      <span>{s.name}</span>
                    </label>
                    <small>{s.result.result ? `${isk(s.result.result.net_profit)} · ${pct(s.result.result.roi)}` : t("sim.incomplete")}</small>
                    <button className="account-btn" onClick={() => void remove(s.id)}>{t("sim.delete")}</button>
                  </li>
                ))}
              </ul>
            )}
            <button className="account-btn" disabled={busy || picked.length < 2 || picked.length > 6} onClick={() => void runCompare()}>
              {t("sim.compare")}
            </button>
            <span className="profile-meta"> {t("sim.compareHint")}</span>
            {compare && (
              <div className="profile-table-wrap">
                <table className="profile-table">
                  <thead><tr><th>{t("sim.scenarioName")}</th><th>{t("sim.r.netProfit")}</th><th>{t("sim.r.roi")}</th><th>{t("sim.r.capitalOutlay")}</th></tr></thead>
                  <tbody>
                    {[...compare].sort((a, b) => ranking.indexOf(a.name) - ranking.indexOf(b.name)).map((c) => (
                      <tr key={c.name} className={ranking[0] === c.name ? "sim-best" : undefined}>
                        <td>{c.name}</td>
                        <td>{c.assessment.result ? isk(c.assessment.result.net_profit) : "—"}</td>
                        <td>{c.assessment.result ? pct(c.assessment.result.roi) : "—"}</td>
                        <td>{c.assessment.result ? isk(c.assessment.result.capital_outlay) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

export function SimulatorButton({ t }: { t: TFunction }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="account-btn" onClick={() => setOpen(true)}>{t("sim.open")}</button>
      {open && <SimulatorPanel t={t} onClose={() => setOpen(false)} />}
    </>
  );
}
