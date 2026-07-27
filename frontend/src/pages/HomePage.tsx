import { Link } from "react-router-dom";
import { useI18n } from "../i18n/useI18n";
import { usePageTitle } from "../i18n/usePageTitle";

export function HomePage() {
  const { t } = useI18n();
  usePageTitle("titles.home");

  return (
    <section className="page-section">
      <div className="section-heading">
        <p className="eyebrow">{t("home.eyebrow")}</p>
        <h1>{t("app.productName")}</h1>
        <p>{t("home.intro")}</p>
      </div>
      <div className="module-grid">
        <Link to="/forward" className="module-card available">
          <span className="status-dot ready" />
          <h2>{t("app.forward")}</h2>
          <p>{t("home.forwardDescription")}</p>
          <span className="card-action">{t("home.forwardAction")}</span>
        </Link>
        <Link to="/reverse" className="module-card available">
          <span className="status-dot ready" />
          <h2>{t("app.reverse")}</h2>
          <p>{t("home.reverseDescription")}</p>
          <span className="card-action">{t("home.reverseAction")}</span>
        </Link>
      </div>
      <p className="supporting-note">{t("home.scope")}</p>
    </section>
  );
}
