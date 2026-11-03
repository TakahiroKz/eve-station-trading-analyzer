import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { I18nContext, type I18nValue } from "./context";
import {
  detectLang, langPath, LOCALES, storeLang, translate, type Lang, type MessageKey,
} from "./index";

function setMeta(selector: string, content: string) {
  document.querySelector(selector)?.setAttribute("content", content);
}

/** Point the address bar at the language's own path, keeping any other query parameter. */
function syncUrl(lang: Lang) {
  const params = new URLSearchParams(window.location.search);
  params.delete("lang"); // old URL form; the path carries the language now
  const rest = params.toString();
  window.history.replaceState(
    null, "", langPath(lang) + (rest ? `?${rest}` : "") + window.location.hash,
  );
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  const setLang = useCallback((next: Lang) => {
    storeLang(next);
    // Keep the choice in the URL so a shared link opens in the same language.
    syncUrl(next);
    setLangState(next);
  }, []);

  useEffect(() => {
    // A link shared in the old `?lang=es` form is rewritten to `/es/` once the app loads.
    if (new URLSearchParams(window.location.search).has("lang")) syncUrl(lang);
  }, [lang]);

  useEffect(() => {
    const text = (key: MessageKey) => translate(lang, key);
    const url = `${window.location.origin}${langPath(lang)}`;
    document.documentElement.lang = lang;
    document.title = text("meta.title");
    setMeta('meta[name="description"]', text("meta.description"));
    setMeta('meta[property="og:title"]', text("meta.title"));
    setMeta('meta[property="og:description"]', text("meta.ogDescription"));
    setMeta('meta[property="og:locale"]', LOCALES[lang].replace("-", "_"));
    setMeta('meta[property="og:url"]', url);
    document.querySelector('link[rel="canonical"]')?.setAttribute("href", url);
  }, [lang]);

  const value = useMemo<I18nValue>(
    () => ({
      lang,
      setLang,
      locale: LOCALES[lang],
      t: (key, vars) => translate(lang, key, vars),
    }),
    [lang, setLang],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
