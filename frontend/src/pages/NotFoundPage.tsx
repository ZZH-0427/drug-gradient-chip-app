import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="page-section narrow">
      <div className="section-heading">
        <p className="eyebrow">Not found</p>
        <h1>页面不存在</h1>
        <p>当前地址没有对应的应用页面。</p>
      </div>
      <div className="action-row">
        <Link className="button primary" to="/">
          返回首页
        </Link>
        <Link className="button secondary" to="/forward">
          进入正向预测
        </Link>
      </div>
    </section>
  );
}
