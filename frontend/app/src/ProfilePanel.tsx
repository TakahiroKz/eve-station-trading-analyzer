// Signed-in player's trading profile: skills and standings read from EVE (or edited by hand), the fees they produce in
// each hub and the wallet balance. Every value says where it comes from; nothing secret is ever handled here.
import { useCallback, useEffect, useState } from "react";
import type { MessageKey, TFunction } from "./i18n";

type Source = "ESI" | "MANUAL" | "DEFAULT";
const SKILLS = ["broker_relations", "advanced_broker_relations", "accounting"] as const;
type SkillKey = (typeof SKILLS)[number];

interface Valued { value: number; source: Source; esi: number | null }
interface MarketInfo {
  market_id: string; name: string; station: string; owner: string;
  standings: { faction: Valued; corp: Valued };
  fees: { broker_fee_pct: number; sales_tax_pct: number; source: string };
}
interface ProfileData {
  sync: { status: string; skills_at: string | null; standings_at: string | null; stale: boolean; missing_scopes: string[] };
  skills: Record<SkillKey, Valued>;
  markets: MarketInfo[];
  has_override: boolean;
}
interface CapitalData { wallet_isk: string | null; wallet_at: string | null }
interface Draft { skills: Record<SkillKey, string>; standings: Record<string, { faction: string; corp: string }> }

const SOURCE_KEY: Record<Source, MessageKey> = {
  ESI: "profile.source.ESI", MANUAL: "profile.source.MANUAL", DEFAULT: "profile.source.DEFAULT",
};
const SKILL_KEY: Record<SkillKey, MessageKey> = {
  broker_relations: "profile.skill.broker_relations",
  advanced_broker_relations: "profile.skill.advanced_broker_relations",
  accounting: "profile.skill.accounting",
};

function draftFrom(data: ProfileData): Draft {
  const skills = {} as Record<SkillKey, string>;
  for (const key of SKILLS) skills[key] = data.skills[key].source === "MANUAL" ? String(data.skills[key].value) : "";
  const standings: Draft["standings"] = {};
  for (const m of data.markets) {
    standings[m.market_id] = {
      faction: m.standings.faction.source === "MANUAL" ? String(m.standings.faction.value) : "",
      corp: m.standings.corp.source === "MANUAL" ? String(m.standings.corp.value) : "",
    };
  }
  return { skills, standings };
}

function overrideBody(draft: Draft) {
  const skills: Record<string, number> = {};
  for (const key of SKILLS) if (draft.skills[key] !== "") skills[key] = Number(draft.skills[key]);
  const standings: Record<string, Record<string, number>> = {};
  for (const [market, v] of Object.entries(draft.standings)) {
    const row: Record<string, number> = {};
    if (v.faction.trim() !== "") row.faction = Number(v.faction);
    if (v.corp.trim() !== "") row.corp = Number(v.corp);
    if (Object.keys(row).length) standings[market] = row;
  }
  return { skills, standings };
}

function validDraft(draft: Draft): boolean {
  return Object.values(draft.standings).every((v) => [v.faction, v.corp].every((s) => {
    if (s.trim() === "") return true;
    const n = Number(s);
    return Number.isFinite(n) && n >= -10 && n <= 10;
  }));
}

export function ProfilePanel({ t, onClose }: { t: TFunction; onClose: () => void }) {
  const [data, setData] = useState<ProfileData | null>(null);
  const [capital, setCapital] = useState<CapitalData | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  const [message, setMessage] = useState<MessageKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([
        fetch("/api/me/profile", { cache: "no-store" }), fetch("/api/me/capital", { cache: "no-store" }),
      ]);
      if (!p.ok) { setError("profile.error"); return; }
      setData((await p.json()) as ProfileData);
      setCapital(c.ok ? ((await c.json()) as CapitalData) : null);
    } catch {
      setError("profile.error");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function send(url: string, init: RequestInit): Promise<boolean> {
    setBusy(true); setMessage(null); setError(null);
    try {
      const response = await fetch(url, init);
      if (response.status === 429) { setMessage("profile.throttled"); return false; }
      if (!response.ok) { setError("profile.error"); return false; }
      setData((await response.json()) as ProfileData);
      return true;
    } catch {
      setError("profile.error");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (await send("/api/me/profile/refresh", { method: "POST" })) {
      setMessage("profile.refreshed");
      void fetch("/api/me/capital", { cache: "no-store" }).then(async (r) => { if (r.ok) setCapital((await r.json()) as CapitalData); });
    }
  }

  async function save(body: unknown) {
    const ok = await send("/api/me/profile/override", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (ok) { setDraft(null); setMessage("profile.saved"); }
  }

  const sync = data?.sync;
  const when = (stamp: string | null) => (stamp ? new Date(stamp).toLocaleString() : "—");
  const notices: MessageKey[] = [];
  if (sync?.status === "REVOKED") notices.push("profile.revoked");
  if (sync?.status === "UNAVAILABLE") notices.push("profile.unavailable");
  if (sync?.stale) notices.push("profile.stale");

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="profile-title">{t("profile.title")}</h2>
        {error && <p className="profile-warn" role="alert">{t(error)}</p>}
        {!data && !error && <p>{t("profile.loading")}</p>}
        {data && sync && (
          <>
            {notices.map((key) => <p key={key} className="profile-warn" role="alert">{t(key)}</p>)}
            {sync.missing_scopes.length > 0 && (
              <p className="profile-warn" role="alert">{t("profile.partial", { scopes: sync.missing_scopes.join(", ") })}</p>
            )}
            <p className="profile-meta">
              {t("profile.updated", { when: when(sync.skills_at) })}
              {" · "}
              {t("profile.wallet")}: {capital?.wallet_isk != null
                ? `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(Number(capital.wallet_isk))} ISK`
                : t("profile.walletNone")}
            </p>

            <h3>{t("profile.skills")}</h3>
            <ul className="profile-skills">
              {SKILLS.map((key) => {
                const s = data.skills[key];
                return (
                  <li key={key}>
                    <span>{t(SKILL_KEY[key])}</span>
                    {draft ? (
                      <select aria-label={t(SKILL_KEY[key])} value={draft.skills[key]}
                        onChange={(e) => setDraft({ ...draft, skills: { ...draft.skills, [key]: e.target.value } })}>
                        <option value="">{t("profile.useEve")}</option>
                        {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
                      </select>
                    ) : (
                      <strong>{s.value} <small className={`src-${s.source}`}>{t(SOURCE_KEY[s.source])}</small></strong>
                    )}
                  </li>
                );
              })}
            </ul>

            <h3>{t("profile.markets")}</h3>
            <div className="profile-table-wrap">
              <table className="profile-table">
                <thead>
                  <tr>
                    <th>{t("profile.col.market")}</th><th>{t("profile.col.factionStanding")}</th>
                    <th>{t("profile.col.corpStanding")}</th><th>{t("profile.col.broker")}</th><th>{t("profile.col.tax")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.markets.map((m) => (
                    <tr key={m.market_id}>
                      <td title={m.station}>{m.name}<small>{m.owner}</small></td>
                      {(["faction", "corp"] as const).map((kind) => (
                        <td key={kind}>
                          {draft ? (
                            <input inputMode="decimal" aria-label={`${m.name} ${t(kind === "faction" ? "profile.col.factionStanding" : "profile.col.corpStanding")}`}
                              placeholder={t("profile.useEve")} value={draft.standings[m.market_id]?.[kind] ?? ""}
                              onChange={(e) => setDraft({ ...draft, standings: { ...draft.standings,
                                [m.market_id]: { ...draft.standings[m.market_id], [kind]: e.target.value } } })} />
                          ) : (
                            <>{m.standings[kind].value}<small className={`src-${m.standings[kind].source}`}>{t(SOURCE_KEY[m.standings[kind].source])}</small></>
                          )}
                        </td>
                      ))}
                      <td>{m.fees.broker_fee_pct}%</td>
                      <td>{m.fees.sales_tax_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="profile-meta">{t("profile.note")}</p>
            {message && <p className="profile-ok" role="status">{t(message)}</p>}

            <div className="modal-actions">
              {draft ? (
                <>
                  <button className="account-btn" disabled={busy} onClick={() => setDraft(null)}>{t("profile.cancel")}</button>
                  <button className="account-btn primary" disabled={busy || !validDraft(draft)} onClick={() => void save(overrideBody(draft))}>{t("profile.save")}</button>
                </>
              ) : (
                <>
                  {data.has_override && <button className="account-btn" disabled={busy} onClick={() => void save({})}>{t("profile.reset")}</button>}
                  <button className="account-btn" disabled={busy} onClick={() => setDraft(draftFrom(data))}>{t("profile.edit")}</button>
                  <button className="account-btn" disabled={busy} onClick={() => void refresh()}>{t("profile.refresh")}</button>
                  <button className="account-btn primary" onClick={onClose}>{t("profile.close")}</button>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
