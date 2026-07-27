import { createContext } from "react";
import { DEFAULT_LOCALE, type Locale } from "./locale";
import { translations } from "./translations";

type TranslationTree = typeof translations[typeof DEFAULT_LOCALE];
type LeafPaths<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string
    ? `${Prefix}${K}`
    : LeafPaths<T[K], `${Prefix}${K}.`>;
}[keyof T & string];

export type TranslationPath = LeafPaths<TranslationTree>;
export type TranslationValues = Record<string, string | number>;

export interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationPath, values?: TranslationValues) => string;
}

export const I18nContext = createContext<I18nContextValue | null>(null);
