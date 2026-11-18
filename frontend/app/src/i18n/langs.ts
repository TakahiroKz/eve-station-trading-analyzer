// The list of languages and where each one lives, with no dependency on the browser or on
// the dictionaries, so the Vite config can use it too (to generate one HTML page per language).

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

/** The trade hubs that have their own public page (`/amarr/`, `/es/amarr/`...), served by the backend. */
export const MARKET_PAGES = [
  { id: "jita", name: "Jita" },
  { id: "amarr", name: "Amarr" },
  { id: "dodixie", name: "Dodixie" },
  { id: "rens", name: "Rens" },
  { id: "hek", name: "Hek" },
] as const;

export function marketPagePath(lang: Lang, marketId: string): string {
  return lang === DEFAULT_LANG ? `/${marketId}/` : `/${lang}/${marketId}/`;
}

/** Each non-default language lives at its own path (`/es/`, `/de/`...) so search engines can
 *  index it; the default one stays at `/`. */
export function langPath(lang: Lang): string {
  return lang === DEFAULT_LANG ? "/" : `/${lang}/`;
}
