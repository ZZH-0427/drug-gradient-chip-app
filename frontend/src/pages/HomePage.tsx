import { Link } from "react-router-dom";

export function HomePage() {
  return (
    <section className="page-section">
      <div className="section-heading">
        <p className="eyebrow">Physics-GNN runtime</p>
        <h1>药物浓度梯度芯片预测系统</h1>
        <p>面向固定6芯片正式模型的正向浓度预测与反向结构设计工具。</p>
      </div>
      <div className="module-grid">
        <Link to="/forward" className="module-card available">
          <span className="status-dot ready" />
          <h2>正向预测</h2>
          <p>输入芯片位置参数，调用正式 Physics-GNN 模型生成6个浓度预测结果。</p>
          <span className="card-action">进入正向预测</span>
        </Link>
        <Link to="/reverse" className="module-card available">
          <span className="status-dot ready" />
          <h2>反向设计</h2>
          <p>输入目标浓度，通过后台异步任务生成一个6芯片结构设计方案。</p>
          <span className="card-action">进入反向设计</span>
        </Link>
      </div>
    </section>
  );
}
