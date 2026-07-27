export type Locale = "zh-CN" | "en";

export const DEFAULT_LOCALE: Locale = "zh-CN";
export const LOCALE_STORAGE_KEY = "drug-gradient-chip.locale";

export function isLocale(value: unknown): value is Locale {
  return value === "zh-CN" || value === "en";
}

export function readStoredLocale(storage: Storage | undefined = safeLocalStorage()): Locale {
  if (!storage) {
    return DEFAULT_LOCALE;
  }
  try {
    const value = storage.getItem(LOCALE_STORAGE_KEY);
    return isLocale(value) ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function writeStoredLocale(locale: Locale, storage: Storage | undefined = safeLocalStorage()) {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // The in-memory React state is still the source of truth for this session.
  }
}

function safeLocalStorage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}
