import { Link } from "react-router-dom";
import { useI18n } from "../i18n/useI18n";
import { usePageTitle } from "../i18n/usePageTitle";

export function NotFoundPage() {
  const { t } = useI18n();
  usePageTitle("titles.notFound");

  return (
    <section className="page-section narrow">
      <div className="section-heading">
        <p className="eyebrow">{t("notFound.eyebrow")}</p>
        <h1>{t("notFound.heading")}</h1>
        <p>{t("notFound.description")}</p>
      </div>
      <div className="action-row">
        <Link className="button primary" to="/">
          {t("common.backToHome")}
        </Link>
        <Link className="button secondary" to="/forward">
          {t("home.forwardAction")}
        </Link>
      </div>
    </section>
  );
}
