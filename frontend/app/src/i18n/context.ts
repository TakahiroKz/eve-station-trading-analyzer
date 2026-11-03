import { createContext } from "react";
import type { Lang, TFunction } from "./index";

export interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** BCP 47 locale for Intl number/date formatting. */
  locale: string;
  t: TFunction;
}

export const I18nContext = createContext<I18nValue | null>(null);
