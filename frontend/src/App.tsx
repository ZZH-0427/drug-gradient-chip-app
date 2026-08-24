import { NavLink, Route, Routes } from "react-router-dom";
import { LanguageSwitcher } from "./i18n/LanguageSwitcher";
import { useI18n } from "./i18n/useI18n";
import { ForwardPage } from "./pages/ForwardPage";
import { ChatPage } from "./pages/ChatPage";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ReversePage } from "./pages/ReversePage";

export default function App() {
  const { t } = useI18n();

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          {t("app.fullName")}
        </NavLink>
        <div className="topbar-actions">
          <nav aria-label={t("app.navLabel")}>
            <NavLink to="/forward">{t("app.forward")}</NavLink>
            <NavLink to="/reverse">{t("app.reverse")}</NavLink>
            <NavLink to="/assistant">{t("assistant.heading")}</NavLink>
          </nav>
          <LanguageSwitcher />
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/forward" element={<ForwardPage />} />
          <Route path="/reverse" element={<ReversePage />} />
          <Route path="/assistant" element={<ChatPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}
