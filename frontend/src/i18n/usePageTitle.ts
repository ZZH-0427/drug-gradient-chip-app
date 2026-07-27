import { useEffect } from "react";
import type { TranslationPath } from "./context";
import { useI18n } from "./useI18n";

export function usePageTitle(titleKey: TranslationPath) {
  const { t } = useI18n();

  useEffect(() => {
    document.title = t(titleKey);
  }, [t, titleKey]);
}
