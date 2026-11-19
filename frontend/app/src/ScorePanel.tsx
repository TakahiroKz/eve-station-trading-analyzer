// Opportunity score (0-100): chip for the table and the "why this score?" panel for the item detail.
// The server computes everything (backend/api/main.py::build_assessment); this file only displays it,
// translating the stable codes it sends (factor notes, filters, reasons) into the visitor's language.
import type { Assessment, ItemStatus, ScoreClass, ScoreFactor } from "./api";
import { en } from "./i18n/en";
import type { MessageKey, TFunction } from "./i18n";

const OK_REASONS = new Set(["SCORE_ABOVE_MINIMUM", "ROI_ABOVE_MINIMUM", "LIQUIDITY_ABOVE_MINIMUM", "HOLDING_TIME_OK"]);

// Translate by code; an unknown code (a newer server) falls back to the server's own text.
function byCode(t: TFunction, prefix: string, code: string, fallback: string, vars?: Record<string, string | number>) {
  const key = `${prefix}.${code}`;
  return key in en ? t(key as MessageKey, vars) : fallback;
}

export function ScoreChip({ score, scoreClass, t }: { score?: number | null; scoreClass?: ScoreClass | null; t: TFunction }) {
  if (score == null) return <span className="score-chip score-none">—</span>;
  const label = scoreClass ? t(`class.${scoreClass}` as MessageKey) : "";
  return <span className={`score-chip score-${scoreClass ?? "none"}`} title={label}>{score}</span>;
}

export function ScorePanel({ status, assessment, t, locale }: {
  status: ItemStatus; assessment: Assessment | null; t: TFunction; locale: string;
}) {
  const int = (n: number | null | undefined) =>
    n == null ? "—" : new Intl.NumberFormat(locale, { maximumFractionDigits: 0, useGrouping: "always" }).format(n);
  const num = (n: number | null | undefined, digits = 1) =>
    n == null ? "—" : new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
  const pct = (n: number | null | undefined, digits = 1) =>
    n == null ? "—" : new Intl.NumberFormat(locale, { style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);

  if (!assessment || status.score == null) {
    return (
      <section className="score-panel">
        <h3>{t("score.title")}</h3>
        <p className="muted">{t("score.noScore")}</p>
      </section>
    );
  }

  const { score, eligibility, recommendation, reference } = assessment;
  const cls = score.classification;

  const factorValue = (f: ScoreFactor) => {
    const m = f.metrics;
    switch (f.key) {
      case "profitability": return t("score.value.profitability", { roi: pct(m.roi) });
      case "liquidity": return t("score.value.liquidity", { position: pct(m.position) });
      case "volume": return t("score.value.volume", { turnover: int(m.turnover) });
      case "book":
        return m.depth_ratio == null
          ? t("score.value.book", { ops: num(m.ops), buy: int(m.buy_orders), sell: int(m.sell_orders) })
          : t("score.value.bookDepth", {
            ops: num(m.ops), buy: int(m.buy_orders), sell: int(m.sell_orders), depth: num(m.depth_ratio),
          });
      case "stability":
        return m.cv == null
          ? t("score.value.stabilityNoCv", { ratio: num(m.ratio, 2) })
          : t("score.value.stability", { cv: pct(m.cv), ratio: num(m.ratio, 2) });
      case "capital":
        return m.days == null
          ? t("score.value.noVolume")
          : t("score.value.capital", { days: num(m.days), daily: pct(m.daily, 2) });
      default: return f.value;
    }
  };

  // Numbers in "what would need to change" carry different units depending on the condition.
  const changeValue = (code: string, v: number | string | null) => {
    if (v == null) return "—";
    if (typeof v === "string") return v;
    if (code === "ROI_BELOW_MINIMUM") return pct(v);
    if (code === "STALE_MARKET_DATA") return `${num(v)} min`;
    if (code === "EXCESSIVE_HOLDING_TIME") return `${num(v)} d`;
    if (code === "NET_PROFIT_BELOW_MINIMUM") return `${int(v)} ISK`;
    return num(v);
  };

  const failed = eligibility.failed_filters;
  const conditions = recommendation.reason_codes.filter((code) => !failed.includes(code));

  return (
    <section className="score-panel">
      <h3>{t("score.title")}</h3>

      <div className="score-head">
        <div className={`score-big score-${cls}`}>
          {status.score}<small>/100</small>
        </div>
        <div className="score-tags">
          <span className={`score-tag score-${cls}`}>{t(`class.${cls}` as MessageKey)}</span>
          <span className={`score-tag elig-${eligibility.status}`}>{t(`elig.${eligibility.status}` as MessageKey)}</span>
          <span className={`score-tag act-${recommendation.action}`}>{t(`action.${recommendation.action}` as MessageKey)}</span>
        </div>
      </div>

      {score.caps.length > 0 && (
        <div className="score-caps">
          <strong>{t("score.capsTitle")}</strong>
          <ul>
            {score.caps.map((cap) => (
              <li key={cap.code}>
                {byCode(t, "score.cap", cap.code, cap.note, { limit: cap.limit ?? "", roi: pct(cap.roi ?? null, 0) })}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ul className="score-factors">
        {score.factors.map((f) => (
          <li key={f.key}>
            <div className="factor-top">
              <span>{t(`score.factor.${f.key}` as MessageKey)}</span>
              <span className="factor-points">{num(f.points)} / {num(f.max, 0)}</span>
            </div>
            <div className="factor-bar" role="img" aria-label={`${num(f.points)} / ${num(f.max, 0)}`}>
              <div className="factor-fill" style={{ width: `${f.max > 0 ? Math.min(100, (f.points / f.max) * 100) : 0}%` }} />
            </div>
            <div className="factor-value">{factorValue(f)}</div>
            <div className="factor-note">{byCode(t, "score.note", f.code, f.note)}</div>
          </li>
        ))}
      </ul>

      {failed.length > 0 && (
        <div className="score-block score-block-bad">
          <strong>{t("score.blockedTitle")}</strong>
          <ul>{failed.map((code) => <li key={code}>✗ {byCode(t, "score.code", code, code)}</li>)}</ul>
        </div>
      )}

      {conditions.length > 0 && (
        <div className="score-block">
          <strong>{t("score.conditionsTitle")}</strong>
          <ul>
            {conditions.map((code) => (
              <li key={code} className={OK_REASONS.has(code) ? "ok" : "bad"}>
                {OK_REASONS.has(code) ? "✓" : "✗"} {byCode(t, "score.code", code, code)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {recommendation.to_change.length > 0 && (
        <div className="score-block">
          <strong>{t("score.needsTitle")}</strong>
          <ul>
            {recommendation.to_change.map((c, i) => {
              const what = byCode(t, "score.code", c.code, c.code);
              // Conditions without numbers (e.g. "the status is Discarded") are just listed.
              if (c.current == null && c.needed == null) return <li key={`${c.code}-${i}`}>{what}</li>;
              return (
                <li key={`${c.code}-${i}`}>
                  {t("score.needsRow", {
                    what: what.replace(/[.。]$/, ""),
                    current: changeValue(c.code, c.current),
                    needed: changeValue(c.code, c.needed),
                  })}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <p className="muted score-small">
        {t("score.reference", { isk: int(reference.position_isk), units: int(reference.quantity) })}
        {assessment.data_age_min != null && assessment.data_age_min > 5 && ` ${t("score.dataAge", { n: int(assessment.data_age_min) })}`}
      </p>
      {assessment.config_changed && <p className="muted score-small">{t("score.configChanged")}</p>}
      <p className="muted score-small">{t("score.help")} {t("score.disclaimer")}</p>
    </section>
  );
}
