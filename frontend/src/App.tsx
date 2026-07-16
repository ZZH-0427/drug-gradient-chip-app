import { NavLink, Route, Routes } from "react-router-dom";
import { ForwardPage } from "./pages/ForwardPage";
import { HomePage } from "./pages/HomePage";
import { ReversePlaceholderPage } from "./pages/ReversePlaceholderPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          药物浓度梯度芯片预测系统
        </NavLink>
        <nav aria-label="主导航">
          <NavLink to="/forward">正向预测</NavLink>
          <NavLink to="/reverse">反向预测</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/forward" element={<ForwardPage />} />
          <Route path="/reverse" element={<ReversePlaceholderPage />} />
        </Routes>
      </main>
    </div>
  );
}
