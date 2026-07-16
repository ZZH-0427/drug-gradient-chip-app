import { Link } from "react-router-dom";

export function HomePage() {
  return (
    <section className="page-section">
      <div className="section-heading">
        <p className="eyebrow">Forward runtime</p>
        <h1>药物浓度梯度芯片预测系统</h1>
        <p>面向芯片结构参数的正向浓度预测工具。</p>
      </div>
      <div className="module-grid">
        <Link to="/forward" className="module-card available">
          <span className="status-dot ready" />
          <h2>正向预测</h2>
          <p>输入六个固定位置的芯片参数，调用已接入的正向模型生成预测结果。</p>
          <span className="card-action">进入正向预测</span>
        </Link>
        <Link to="/reverse" className="module-card muted">
          <span className="status-dot pending" />
          <h2>反向预测</h2>
          <p>反向模型尚未接入，当前版本仅开放正向预测流程。</p>
          <span className="card-action">查看接入状态</span>
        </Link>
      </div>
    </section>
  );
}
