// "Your capital" selector: the score is recomputed by the server for this capital (liquidity, book depth and
// capital efficiency depend on it; margin and stability do not). null = the stored reference capital.
import { useState } from "react";
import type { MessageKey, TFunction } from "./i18n";

export const REFERENCE_CAPITAL = 1_000_000_000; // the capital the stored score is measured with (1,000 M ISK)
export const MIN_CAPITAL = 1_000_000;
export const MAX_CAPITAL = 1e13;
const POSITION_FRACTION = 0.1; // one position uses a tenth of the capital (backend default setting)
const PRESETS = [50_000_000, 250_000_000, 5_000_000_000];
const CUSTOM = "custom";

export function CapitalPicker({ value, onChange, t, locale }: {
  value: number | null; onChange: (capital: number | null) => void; t: TFunction; locale: string;
}) {
  const millions = (n: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 3, useGrouping: "always" }).format(n / 1e6);
  const isk = (n: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 0, useGrouping: "always" }).format(n);
  const isPreset = value == null || PRESETS.includes(value) || value === REFERENCE_CAPITAL;
  const [customMode, setCustomMode] = useState(!isPreset);
  const [draft, setDraft] = useState(value != null && !isPreset ? String(value / 1e6) : "");

  const selected = customMode ? CUSTOM : String(value ?? REFERENCE_CAPITAL);

  function pick(choice: string) {
    if (choice === CUSTOM) {
      setCustomMode(true);
      return;
    }
    setCustomMode(false);
    const n = Number(choice);
    onChange(n === REFERENCE_CAPITAL ? null : n);
  }

  function commitDraft() {
    const n = Number(draft.replace(",", ".")) * 1e6;
    if (!Number.isFinite(n) || n < MIN_CAPITAL || n > MAX_CAPITAL) return;
    onChange(n);
  }

  return (
    <div className="capital-picker" title={t("capital.help")}>
      <label>
        <span className="capital-label">{t("capital.label")}</span>
        <select value={selected} onChange={(e) => pick(e.target.value)}>
          {[...PRESETS.slice(0, 2), REFERENCE_CAPITAL, PRESETS[2]].map((n) => (
            <option key={n} value={n}>
              {n === REFERENCE_CAPITAL
                ? t("capital.default", { n: millions(n) })
                : t("capital.millions", { n: millions(n) })}
            </option>
          ))}
          <option value={CUSTOM}>{t("capital.custom")}</option>
        </select>
      </label>
      {customMode && (
        <input
          type="number" min={1} step="any" inputMode="decimal" value={draft}
          placeholder={t("capital.customLabel")} aria-label={t("capital.customLabel")}
          onChange={(e) => setDraft(e.target.value)} onBlur={commitDraft}
          onKeyDown={(e) => { if (e.key === "Enter") commitDraft(); }}
        />
      )}
      {value != null && (
        <span className="capital-note">
          {t("capital.note", { isk: isk(value), position: isk(value * POSITION_FRACTION) } as Record<string, string>)}
          {" "}
          <button className="capital-reset" onClick={() => { setCustomMode(false); onChange(null); }}>
            {t("capital.reset" as MessageKey)}
          </button>
        </span>
      )}
    </div>
  );
}
