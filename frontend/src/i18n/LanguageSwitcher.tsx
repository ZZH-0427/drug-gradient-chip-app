import { useI18n } from "./useI18n";

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="language-switcher" role="group" aria-label={t("app.languageLabel")}>
      <button
        type="button"
        className={locale === "zh-CN" ? "active" : ""}
        aria-pressed={locale === "zh-CN"}
        onClick={() => setLocale("zh-CN")}
      >
        {t("language.chinese")}
      </button>
      <button
        type="button"
        className={locale === "en" ? "active" : ""}
        aria-pressed={locale === "en"}
        onClick={() => setLocale("en")}
      >
        {t("language.english")}
      </button>
    </div>
  );
}
