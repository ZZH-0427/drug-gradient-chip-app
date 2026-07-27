import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { type Locale, readStoredLocale, writeStoredLocale } from "./locale";
import { I18nContext, type TranslationPath, type TranslationValues } from "./context";
import { translations } from "./translations";

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => readStoredLocale());

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    writeStoredLocale(nextLocale);
  }, []);

  const t = useCallback(
    (key: TranslationPath, values?: TranslationValues) => {
      const template = readTranslation(translations[locale], key);
      return interpolate(template, values);
    },
    [locale],
  );

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

function readTranslation(tree: object, key: TranslationPath): string {
  const value = key.split(".").reduce<unknown>((current, segment) => {
    if (current && typeof current === "object" && segment in current) {
      return (current as Record<string, unknown>)[segment];
    }
    return undefined;
  }, tree);

  if (typeof value !== "string") {
    throw new Error(`Missing translation key: ${key}`);
  }
  return value;
}

function interpolate(template: string, values?: TranslationValues): string {
  if (!values) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, key) =>
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match,
  );
}
