import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { I18nContext, type I18nValue } from "./context";
import { detectLang, LOCALES, storeLang, translate, type Lang, type MessageKey } from "./index";

function setMeta(selector: string, content: string) {
  document.querySelector(selector)?.setAttribute("content", content);
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang);

  const setLang = useCallback((next: Lang) => {
    storeLang(next);
    // Keep the choice in the URL so a shared link opens in the same language.
    const params = new URLSearchParams(window.location.search);
    params.set("lang", next);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    setLangState(next);
  }, []);

  useEffect(() => {
    const text = (key: MessageKey) => translate(lang, key);
    document.documentElement.lang = lang;
    document.title = text("meta.title");
    setMeta('meta[name="description"]', text("meta.description"));
    setMeta('meta[property="og:title"]', text("meta.title"));
    setMeta('meta[property="og:description"]', text("meta.ogDescription"));
    setMeta('meta[property="og:locale"]', LOCALES[lang].replace("-", "_"));
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
