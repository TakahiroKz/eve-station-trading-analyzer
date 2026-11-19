// "Your capital" selector, drawn like the market selector (uppercase label + pills). The server recomputes the
// score and the suggested units for this capital; one position uses POSITION_FRACTION of it. null = the stored
// reference capital.
import { useState } from "react";
import type { MessageKey, TFunction } from "./i18n";

export const REFERENCE_CAPITAL = 1_000_000_000; // the capital the stored score is measured with (1,000 M ISK)
export const MIN_CAPITAL = 1_000_000;
export const MAX_CAPITAL = 1e13;
export const POSITION_FRACTION = 0.1; // one position uses a tenth of the capital (server default setting)
// The server rounds the capital to 2 significant digits (123 M -> 120 M); the picker does the same so that what it
// shows is what the score and the recommendation are calculated for.
export function snapCapital(n: number): number {
  const step = 10 ** (Math.floor(Math.log10(n)) - 1);
  return Math.round(n / step) * step;
}

const PRESETS = [50_000_000, 250_000_000, REFERENCE_CAPITAL, 5_000_000_000];

export function CapitalPicker({ value, onChange, t, locale }: {
  value: number | null; onChange: (capital: number | null) => void; t: TFunction; locale: string;
}) {
  const current = value ?? REFERENCE_CAPITAL;
  const isPreset = PRESETS.includes(current);
  const [customMode, setCustomMode] = useState(!isPreset);
  const [draft, setDraft] = useState(!isPreset ? String(current / 1e6) : "");

  const millions = (n: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 3, useGrouping: "always" }).format(n / 1e6);
  const isk = (n: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 0, useGrouping: "always" }).format(n);
  const pct = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(POSITION_FRACTION);

  function pick(n: number) {
    setCustomMode(false);
    onChange(n === REFERENCE_CAPITAL ? null : n);
  }

  function commitDraft() {
    const typed = Number(draft.replace(",", ".")) * 1e6;
    if (!Number.isFinite(typed) || typed < MIN_CAPITAL || typed > MAX_CAPITAL) return;
    const n = snapCapital(typed);
    setDraft(String(n / 1e6));
    onChange(n === REFERENCE_CAPITAL ? null : n);
  }

  return (
    <div className="capital-block">
      <div className="market-switch" role="group" aria-label={t("capital.label")} title={t("capital.help")}>
        <span className="market-switch-label">{t("capital.label")}</span>
        {PRESETS.map((n) => (
          <button
            key={n}
            className={!customMode && current === n ? "tab active" : "tab"}
            aria-pressed={!customMode && current === n}
            title={t("capital.pillTitle", { position: isk(n * POSITION_FRACTION) })}
            onClick={() => pick(n)}
          >
            {t("capital.pill", { n: millions(n) })}
          </button>
        ))}
        <button
          className={customMode ? "tab active" : "tab"}
          aria-pressed={customMode}
          onClick={() => { setDraft(String(current / 1e6)); setCustomMode(true); }}
        >
          {t("capital.custom")}
        </button>
        {customMode && (
          <>
            <input
              className="filter-quick capital-input"
              type="number" min={1} step="any" inputMode="decimal" value={draft}
              placeholder={t("capital.customLabel")} aria-label={t("capital.customLabel")}
              onChange={(e) => setDraft(e.target.value)} onBlur={commitDraft}
              onKeyDown={(e) => { if (e.key === "Enter") commitDraft(); }}
            />
            <span className="capital-suffix">{t("capital.customSuffix")}</span>
          </>
        )}
      </div>
      <p className="capital-position">
        <strong>{t("capital.position", { pct, position: isk(current * POSITION_FRACTION) })}</strong>
        {" · "}
        {t((value == null ? "capital.basisDefault" : "capital.basis") as MessageKey, { isk: isk(current) })}
        {value != null && (
          <>
            {" "}
            <button className="capital-reset" onClick={() => { setCustomMode(false); onChange(null); }}>
              {t("capital.reset")}
            </button>
          </>
        )}
      </p>
    </div>
  );
}
