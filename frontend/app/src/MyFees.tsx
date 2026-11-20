// "My fees" switch for the Screener: when signed in, the list and the item detail are recalculated by the server with the
// player's own broker fee and sales tax (from their EVE skills and standings) instead of the reference fees.
import { useEffect, useState } from "react";
import type { MessageKey, TFunction } from "./i18n";

export interface FeeProfileInfo {
  broker_fee_pct: number; sales_tax_pct: number; source: string; market_id: string; station: string; personalized: boolean;
}

const KEY = "useMyFees";

const SIGNED_KEY = "signedIn";

// Whether the visitor has an account session. The last known answer is kept so that the capital selector does not flash
// in and out on every page load for someone who is signed in (or the other way round); the server answer then replaces it.
export function useSignedIn(): boolean {
  const [signedIn, setSignedIn] = useState<boolean>(() => {
    try { return window.localStorage.getItem(SIGNED_KEY) === "1"; } catch { return false; }
  });
  useEffect(() => {
    void fetch("/api/auth/status", { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as { authenticated: boolean; needs_consent?: boolean }) : null))
      .then((s) => {
        const ok = !!s && s.authenticated && !s.needs_consent;
        setSignedIn(ok);
        try { window.localStorage.setItem(SIGNED_KEY, ok ? "1" : "0"); } catch { /* optional */ }
      })
      .catch(() => { /* keep the last known answer */ });
  }, []);
  return signedIn;
}

// The signed-in player's wallet balance (ISK), read through the server (cached 5 min there) and refreshed every 10 min; it
// replaces the capital the visitor would otherwise type. null = no session or the balance could not be read.
export function useWalletCapital(signedIn: boolean): number | null {
  const [wallet, setWallet] = useState<number | null>(null);
  useEffect(() => {
    if (!signedIn) return;
    let alive = true;
    const load = () => {
      void fetch("/api/me/capital", { cache: "no-store" })
        .then(async (r) => (r.ok ? ((await r.json()) as { wallet_isk: string | null }) : null))
        .then((d) => { if (alive && d) setWallet(d.wallet_isk != null && Number.isFinite(Number(d.wallet_isk)) ? Number(d.wallet_isk) : null); })
        .catch(() => { /* keep the previous value */ });
    };
    load();
    const timer = window.setInterval(load, 600_000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [signedIn]);
  return signedIn ? wallet : null;
}

export function readUseMyFees(): boolean {
  try { return window.localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function storeUseMyFees(on: boolean) {
  try { window.localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* the choice then lasts until the page closes */ }
}

export function MyFeesSwitch({ on, onChange, info, t }: {
  on: boolean; onChange: (next: boolean) => void; info: FeeProfileInfo | null; t: TFunction;
}) {
  const note: MessageKey | null = !on ? null : info && !info.personalized ? "myfees.same" : null;
  return (
    <div className="myfees">
      <label className="myfees-toggle" title={t("myfees.help")}>
        <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
        <span>{t("myfees.label")}</span>
      </label>
      {on && info && (
        <span className="myfees-info" role="status">
          {t("myfees.active", { broker: info.broker_fee_pct, tax: info.sales_tax_pct })}
          {note && <> · {t(note)}</>}
        </span>
      )}
    </div>
  );
}
