import { de } from "./de";
import { en, type MessageKey, type Messages } from "./en";
import { es } from "./es";
import { fr } from "./fr";
import { it } from "./it";

export type { MessageKey };
export type Lang = "en" | "es" | "de" | "fr" | "it";

// Native names, so someone who cannot read the current language can still find theirs.
export const LANGS: { code: Lang; label: string }[] = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Français" },
  { code: "it", label: "Italiano" },
];

// English is the default: used when nothing is stored and the browser language is not
// one of the supported ones.
export const DEFAULT_LANG: Lang = "en";

export const LOCALES: Record<Lang, string> = {
  en: "en-US", es: "es-ES", de: "de-DE", fr: "fr-FR", it: "it-IT",
};

const DICTS: Record<Lang, Messages> = { en, es, de, fr, it };
const STORAGE_KEY = "lang";

export type TFunction = (key: MessageKey, vars?: Record<string, string | number>) => string;

export function isLang(value: unknown): value is Lang {
  return typeof value === "string" && value in DICTS;
}

export function translate(lang: Lang, key: MessageKey, vars?: Record<string, string | number>): string {
  const template = DICTS[lang][key] ?? en[key];
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

export function readStoredLang(): Lang | null {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isLang(stored) ? stored : null;
  } catch {
    return null; // storage can be blocked (private mode, disabled cookies)
  }
}

export function storeLang(lang: Lang): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // The choice just won't be remembered.
  }
}

/** Priority: `?lang=xx` in the URL (shareable, what hreflang points to) > the manual choice
 *  remembered in localStorage > the browser language > English. */
export function detectLang(): Lang {
  const fromUrl = new URLSearchParams(window.location.search).get("lang");
  if (isLang(fromUrl)) return fromUrl;

  const stored = readStoredLang();
  if (stored) return stored;

  for (const candidate of navigator.languages ?? [navigator.language]) {
    const prefix = candidate.toLowerCase().split("-")[0];
    if (isLang(prefix)) return prefix;
  }
  return DEFAULT_LANG;
}

// --- Text that comes from the backend ---------------------------------------------------
// The engines store Spanish phrases (spread/liquidity labels, recommendations, the reason
// for a classification). Rather than change the API contract, the known phrases are matched
// here and rendered in the chosen language; anything unrecognized is shown as received.

function labelKey(prefix: "spread" | "liquidity", spanish: string): MessageKey | null {
  for (const key of Object.keys(es) as MessageKey[]) {
    if (key.startsWith(`${prefix}.`) && es[key] === spanish) return key;
  }
  return null;
}

export function translateSpread(t: TFunction, label: string): string {
  const key = labelKey("spread", label);
  return key ? t(key) : label;
}

export function translateLiquidity(t: TFunction, label: string): string {
  const key = labelKey("liquidity", label);
  return key ? t(key) : label;
}

const REC_STATIC: [string, MessageKey][] = [
  [es["rec.noTrade"], "rec.noTrade"],
  [es["rec.keep"], "rec.keep"],
  [es["rec.veryFavorable"], "rec.veryFavorable"],
];

const NUM = "([\\d,]+)";

export function translateRecommendation(t: TFunction, text: string, locale: string): string {
  for (const [spanish, key] of REC_STATIC) {
    if (text === spanish) return t(key);
  }
  const units = (raw: string) => new Intl.NumberFormat(locale).format(Number(raw.replace(/,/g, "")));
  let m = text.match(new RegExp(
    `^Hay margen para escalar el volumen deseado hasta ~${NUM} unidades \\((\\d+%) del volumen diario\\) sin salir de una liquidez 'Buena'\\.$`));
  if (m) return t("rec.scale", { n: units(m[1]), pct: m[2] });
  m = text.match(new RegExp(
    `^Recorta el volumen hacia ~${NUM} unidades \\((\\d+%) del volumen diario\\) para mejorar la rotación\\.$`));
  if (m) return t("rec.trim", { n: units(m[1]), pct: m[2] });
  m = text.match(new RegExp(
    `^Baja el volumen objetivo a ~${NUM} unidades \\((\\d+%) del volumen diario\\)\\. ` +
    `Con (\\d+%) del volumen diario el capital puede quedar inmovilizado varios días\\.$`));
  if (m) return t("rec.lower", { n: units(m[1]), pct: m[2], pos: m[3] });
  return text;
}

export function translateReason(t: TFunction, text: string): string {
  const sp = (label: string) => translateSpread(t, label);
  const lq = (label: string) => translateLiquidity(t, label);

  let m = text.match(/^Spread '(.+)' y\/o liquidez '(.+)' no viables\.$/);
  if (m) return t("reason.notViable", { spread: sp(m[1]), liquidity: lq(m[2]) });

  m = text.match(/^Spread '(.+)' con liquidez '(.+)': cumple ambos criterios\.$/);
  if (m) return t("reason.meets", { spread: sp(m[1]), liquidity: lq(m[2]) });

  m = text.match(/^Spread '(.+)' \/ liquidez '(.+)': borderline, requiere más historial\.$/);
  if (m) return t("reason.watch", { spread: sp(m[1]), liquidity: lq(m[2]) });

  m = text.match(
    /^Spread '(.+)' y liquidez '(.+)' cumplen, pero el histórico de transacciones \(7 días\) no alcanza: (.+)\. No hay evidencia de flujo real de compradores\.$/,
  );
  if (m) {
    const parts = m[3].split(" y ").map((part) => {
      const vol = part.match(/^([\d.]+) unidades\/día \(mínimo ([\d.]+)\)$/);
      if (vol) return t("reason.failVolume", { value: vol[1], min: vol[2] });
      const ord = part.match(/^([\d.]+) operaciones\/día \(mínimo ([\d.]+)\)$/);
      if (ord) return t("reason.failOrders", { value: ord[1], min: ord[2] });
      return null;
    });
    if (parts.every((p): p is string => p !== null)) {
      return t("reason.noFlow", {
        spread: sp(m[1]), liquidity: lq(m[2]), failures: parts.join(t("reason.failJoin")),
      });
    }
    return text;
  }

  m = text.match(
    /^best_buy\/best_sell \((.+)\/(.+)\) muy alejados del precio histórico reciente \((.+)\): probable orden basura, no es una oportunidad real\.$/,
  );
  if (m) return t("reason.junk", { buy: m[1], sell: m[2], ref: m[3] });

  return text;
}

const SETTING_CATEGORIES: Record<string, MessageKey> = {
  "Clasificación": "setting.cat.classification",
  "Fees de EVE": "setting.cat.fees",
  "Umbrales de spread": "setting.cat.spread",
  "Umbrales de liquidez": "setting.cat.liquidity",
  "Tamaño de posición": "setting.cat.position",
  "Recomendación de volumen": "setting.cat.recommendation",
  "Filtro de órdenes basura": "setting.cat.junk",
};

export function translateSettingCategory(t: TFunction, category: string): string {
  const key = SETTING_CATEGORIES[category];
  return key ? t(key) : category;
}

export function translateSettingLabel(t: TFunction, settingKey: string, fallback: string): string {
  const key = `setting.${settingKey}` as MessageKey;
  return key in en ? t(key) : fallback;
}
