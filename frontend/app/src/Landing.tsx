import type { ItemStatus, Status } from "./api";
import { DONATE_URL } from "./config";
import { LANGS, langPath, type Lang, type MessageKey, type TFunction } from "./i18n";

// The public landing around the Screener (design B): what the site is, live numbers, the best
// opportunities, how to read the statuses, a donation prompt and the footer. Every text comes
// from the i18n dictionaries; the same keys feed the <noscript> block of each language page
// (see the `language-pages` plugin in vite.config.ts).

/** The "Best right now" cards list the most-traded items whose ROI exceeds this fraction (0.165 = 16.5 %). */
export const BEST_MIN_ROI = 0.165;
export const BEST_COUNT = 4;

const STATUSES: Status[] = ["POTENCIAL", "POTENCIAL_SIN_ORDENES", "EN_OBSERVACION", "DESCARTADO"];

export function Hero({ t }: { t: TFunction }) {
  return (
    <section className="hero">
      <p className="hero-eyebrow">{t("hero.eyebrow")}</p>
      <h1 className="hero-title">{t("hero.title")}</h1>
      <p className="hero-subtitle">{t("hero.subtitle")}</p>
      <div className="hero-actions">
        <a className="btn-cta" href="#screener">{t("hero.cta")}</a>
        <a className="btn-ghost" href="#how-it-works">{t("hero.ctaHow")}</a>
      </div>
    </section>
  );
}

export function Stats({ t, opportunities, analyzed, nextRefresh }: {
  t: TFunction;
  opportunities: string;
  analyzed: string;
  nextRefresh: string;
}) {
  return (
    <section className="stats" aria-label={t("stats.refresh")}>
      <div className="stat-card">
        <span className="stat-label">{t("stats.opportunities")}</span>
        <span className="stat-value positive">{opportunities}</span>
      </div>
      <div className="stat-card">
        <span className="stat-label">{t("stats.analyzed")}</span>
        <span className="stat-value">{analyzed}</span>
      </div>
      <div className="stat-card">
        <span className="stat-label">{t("stats.refresh")}</span>
        <span className="stat-value">{t("stats.every4h")}</span>
      </div>
      <div className="stat-card">
        <span className="stat-label">{t("stats.next")}</span>
        <span className="stat-value">{nextRefresh}</span>
      </div>
    </section>
  );
}

export function BestNow({ t, items, formatPrice, formatRoi, formatCount, onOpen }: {
  t: TFunction;
  items: ItemStatus[];
  formatPrice: (value: number) => string;
  formatRoi: (value: number) => string;
  formatCount: (value: number) => string;
  onOpen: (typeId: number) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="best" aria-labelledby="best-title">
      <div className="section-head">
        <h2 id="best-title" className="section-heading">{t("best.title")}</h2>
      </div>
      <div className="best-grid">
        {items.map((item) => (
          <button key={item.type_id} className="best-card" onClick={() => onOpen(item.type_id)}>
            <span className="best-name">{item.name}</span>
            <span className="best-sub">
              {item.category_name ?? "—"} · {t("screener.tradesPerDay", { n: formatCount(item.avg_daily_order_count_7d) })}
            </span>
            <span className="best-roi">+{formatRoi(item.roi)}</span>
            <span className="best-prices">{formatPrice(item.best_buy)} → {formatPrice(item.best_sell)} ISK</span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function HowItWorks({ t }: { t: TFunction }) {
  return (
    <section id="how-it-works" className="how" aria-labelledby="how-title">
      <h2 id="how-title" className="section-heading">{t("how.title")}</h2>
      <div className="how-steps">
        {[1, 2, 3].map((n) => (
          <div key={n} className="how-step">
            <span className="how-num">0{n}</span>
            <h3>{t(`how.step${n}.title` as MessageKey)}</h3>
            <p>{t(`how.step${n}.body` as MessageKey)}</p>
          </div>
        ))}
      </div>
      <h3 className="how-states-title">{t("how.statesTitle")}</h3>
      <div className="how-states">
        {STATUSES.map((status) => (
          <div key={status} className={status === "POTENCIAL" ? "how-state is-potential" : "how-state"}>
            <b>{t(`tab.${status}` as MessageKey)}</b>
            <p>{t(`how.stateBody.${status}` as MessageKey)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function SupportBand({ t }: { t: TFunction }) {
  if (!DONATE_URL) return null;
  return (
    <section className="support" aria-labelledby="support-title">
      <div>
        <h2 id="support-title" className="section-heading">{t("support.title")}</h2>
        <p>{t("support.body")}</p>
      </div>
      <a className="btn-cta btn-cta-cyan" href={DONATE_URL} target="_blank" rel="noopener noreferrer">
        {t("footer.donate")}
      </a>
    </section>
  );
}

export function SiteFooter({ t, lang, setLang, loginUrl, showLogin }: {
  t: TFunction;
  lang: Lang;
  setLang: (lang: Lang) => void;
  loginUrl: string;
  showLogin: boolean;
}) {
  return (
    <footer className="site-footer">
      <p className="footer-disclaimer">{t("footer.disclaimer")}</p>
      <nav className="footer-links" aria-label="Footer">
        {/* A real page (server-rendered, crawlable) listing every item the Screener tracks. */}
        <a href="/items">{t("nav.allItems")}</a>
        <a href="/privacy">{t("nav.privacy")}</a>
        {showLogin && <a href={loginUrl}>{t("nav.login")}</a>}
        {LANGS.map((l) => (
          <a
            key={l.code}
            href={langPath(l.code)}
            hrefLang={l.code}
            aria-current={l.code === lang ? "true" : undefined}
            onClick={(e) => { e.preventDefault(); setLang(l.code); }}
          >
            {l.label}
          </a>
        ))}
      </nav>
    </footer>
  );
}
