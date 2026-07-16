import { Link } from "react-router-dom";

export function ReversePlaceholderPage() {
  return (
    <section className="page-section narrow">
      <div className="section-heading">
        <p className="eyebrow">Reverse runtime</p>
        <h1>反向预测尚未接入</h1>
        <p>当前系统只集成了正向预测模型，反向模型逻辑和运行时接口尚不可用。</p>
      </div>
      <div className="action-row">
        <Link className="button primary" to="/forward">
          前往正向预测
        </Link>
        <Link className="button secondary" to="/">
          返回首页
        </Link>
      </div>
    </section>
  );
}
