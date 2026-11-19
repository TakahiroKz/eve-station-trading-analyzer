// The "Recommendation" box of the item detail: how many units to buy with the chosen capital (one position uses
// 10% of it), what that costs and earns, and why it is held back when the engine does not recommend buying.
// The server computes everything (backend/api/main.py::build_unit_recommendation); this only shows it.
import type { UnitRecommendation } from "./api";
import { en } from "./i18n/en";
import { translateRecommendation, type MessageKey, type TFunction } from "./i18n";

export function UnitRecommendationBox({ reco, t, locale, formatIsk }: {
  reco: UnitRecommendation; t: TFunction; locale: string; formatIsk: (n: number | null | undefined) => string;
}) {
  const days = reco.dias_rotacion == null
    ? "—"
    : t("detail.recDays", { n: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(reco.dias_rotacion) });
  const rejected = reco.action === "REJECT";
  const blocked = reco.blocked_by.map((code) => {
    const key = `score.code.${code}`;
    return [code, key in en ? t(key as MessageKey) : code] as const;
  });
  const tone = rejected ? " is-reject" : reco.action === "WAIT" ? " is-wait" : "";

  return (
    <div className={`recommendation${tone}`}>
      <strong>{t("detail.recommendation")}</strong>{" "}
      {rejected ? t("detail.recBlocked") : translateRecommendation(t, reco.recomendacion, locale)}
      {rejected && (
        <ul className="rec-blocked">
          {blocked.map(([code, text]) => <li key={code}>✗ {text}</li>)}
        </ul>
      )}
      {reco.action === "WAIT" && <p className="rec-note">{t("detail.recWait")}</p>}
      {!rejected && (
        <div className="rec-figures">
          <div><span className="label">{t("detail.recUnits")}</span>{formatIsk(reco.unidades_sugeridas)} u</div>
          <div><span className="label">{t("detail.recInvest")}</span>≈ {formatIsk(reco.inversion_isk)} ISK</div>
          <div><span className="label">{t("detail.recProfit")}</span>≈ {formatIsk(reco.beneficio_neto_isk)} ISK</div>
          <div><span className="label">{t("detail.recRotation")}</span>{days}</div>
        </div>
      )}
      <p className="rec-basis">
        {t("detail.recBasis", { isk: formatIsk(reco.capital), position: formatIsk(reco.posicion_isk) })}
      </p>
    </div>
  );
}
