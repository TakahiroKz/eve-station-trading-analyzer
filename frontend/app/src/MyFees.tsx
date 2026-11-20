// "My fees" switch for the Screener: when signed in, the list and the item detail are recalculated by the server with the
// player's own broker fee and sales tax (from their EVE skills and standings) instead of the reference fees.
import { useEffect, useState } from "react";
import type { MessageKey, TFunction } from "./i18n";

export interface FeeProfileInfo {
  broker_fee_pct: number; sales_tax_pct: number; source: string; market_id: string; station: string; personalized: boolean;
}

const KEY = "useMyFees";

// Whether the visitor has an account session (the switch only exists then).
export function useSignedIn(): boolean {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    void fetch("/api/auth/status", { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as { authenticated: boolean; needs_consent?: boolean }) : null))
      .then((s) => setSignedIn(!!s && s.authenticated && !s.needs_consent))
      .catch(() => setSignedIn(false));
  }, []);
  return signedIn;
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
