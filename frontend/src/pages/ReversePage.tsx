import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiClientError,
  cancelReverseTask,
  createReverseTask,
  getReverseTask,
} from "../api/client";
import type { ReverseDesignRequest, ReverseTaskStatusResponse } from "../api/types";
import {
  REVERSE_TARGET_COUNT,
  cloneDefaultReverseRequest,
  validateReverseRequest,
} from "../domain/reverse";

function formatNumber(value: number, digits = 6) {
  return Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function statusText(status: string | undefined) {
  switch (status) {
    case "queued":
      return "排队中";
    case "running":
      return "运行中";
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    case "cancelled":
      return "已取消";
    default:
      return "未提交";
  }
}

export function ReversePage() {
  const [form, setForm] = useState<ReverseDesignRequest>(() => cloneDefaultReverseRequest());
  const [task, setTask] = useState<ReverseTaskStatusResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const pollingRef = useRef<number | null>(null);

  const validationErrors = useMemo(() => validateReverseRequest(form), [form]);
  const isRunning = task?.status === "queued" || task?.status === "running";

  useEffect(() => {
    if (!isRunning || !task?.task_id) {
      return;
    }
    pollingRef.current = window.setInterval(async () => {
      try {
        const next = await getReverseTask(task.task_id);
        setTask(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : "轮询反向任务失败。");
      }
    }, 3000);
    return () => {
      if (pollingRef.current !== null) {
        window.clearInterval(pollingRef.current);
      }
    };
  }, [isRunning, task?.task_id]);

  function updateTarget(index: number, value: string) {
    const next = [...form.target_concentrations];
    next[index] = Number(value);
    setForm({ ...form, target_concentrations: next });
  }

  async function submit() {
    setError("");
    if (validationErrors.length > 0) {
      setError(validationErrors[0]);
      return;
    }
    setSubmitting(true);
    try {
      const created = await createReverseTask(form);
      setTask({
        task_id: created.task_id,
        status: created.status,
        created_at: new Date().toISOString(),
        warnings: [],
      });
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "创建反向设计任务失败。");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancel() {
    if (!task?.task_id) {
      return;
    }
    setError("");
    try {
      setTask(await cancelReverseTask(task.task_id));
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "取消反向设计任务失败。");
    }
  }

  function restoreExample() {
    setForm(cloneDefaultReverseRequest());
    setError("");
  }

  return (
    <section className="page-section">
      <div className="section-heading compact">
        <p className="eyebrow">Reverse design</p>
        <h1>反向设计</h1>
        <p>输入6个目标浓度，后台运行固定6芯片 Physics-GNN tandem 反向优化。</p>
      </div>

      <div className="status-banner ready">
        <span className="status-dot ready" />
        <span>异步任务模式，同一时间最多运行1个反向设计任务。</span>
      </div>

      {error ? <div className="message error">{error}</div> : null}
      {validationErrors.length > 0 ? (
        <div className="message inline-warning">{validationErrors[0]}</div>
      ) : null}

      <div className="tool-panel">
        <div className="form-grid">
          <label>
            入口1浓度
            <input
              type="number"
              step="0.01"
              value={form.inlet1}
              disabled={isRunning}
              onChange={(event) => setForm({ ...form, inlet1: Number(event.target.value) })}
            />
          </label>
          <label>
            入口2浓度
            <input
              type="number"
              step="0.01"
              value={form.inlet2}
              disabled={isRunning}
              onChange={(event) => setForm({ ...form, inlet2: Number(event.target.value) })}
            />
          </label>
        </div>

        <div className="table-wrap">
          <table className="input-table">
            <thead>
              <tr>
                <th>位置</th>
                <th>点位</th>
                <th>目标浓度</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: REVERSE_TARGET_COUNT }, (_, index) => (
                <tr key={index}>
                  <td>位置 {index + 1}</td>
                  <td>y{index + 1}</td>
                  <td>
                    <label className="sr-label">
                      y{index + 1}目标浓度
                      <input
                        aria-label={`y${index + 1}目标浓度`}
                        type="number"
                        step="0.01"
                        value={form.target_concentrations[index]}
                        disabled={isRunning}
                        onChange={(event) => updateTarget(index, event.target.value)}
                      />
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="action-row">
          <button
            className="primary"
            type="button"
            disabled={submitting || isRunning || validationErrors.length > 0}
            onClick={submit}
          >
            提交反向设计任务
          </button>
          <button className="secondary" type="button" disabled={isRunning} onClick={restoreExample}>
            恢复官方示例
          </button>
          {isRunning ? (
            <button className="secondary" type="button" onClick={cancel}>
              取消任务
            </button>
          ) : null}
        </div>
      </div>

      {task ? (
        <section className="tool-panel results-panel">
          <div className="result-heading">
            <div>
              <h2>任务状态</h2>
              <p>
                {statusText(task.status)}
                {task.elapsed_seconds ? `，耗时 ${formatNumber(task.elapsed_seconds, 2)} 秒` : ""}
              </p>
            </div>
          </div>
          {task.error ? <div className="message error">{task.error.message}</div> : null}
          {task.warnings.map((warning) => (
            <div className="message inline-warning" key={warning}>
              {warning}
            </div>
          ))}

          {task.result ? (
            <>
              <div className="metric-grid">
                <div>MAE: {formatNumber(task.result.metrics.mae)}</div>
                <div>RMSE: {formatNumber(task.result.metrics.rmse)}</div>
                <div>MaxAE: {formatNumber(task.result.metrics.maxae)}</div>
                <div>内部筛选: {task.result.metrics.internal_screening_pass ? "通过" : "未通过"}</div>
              </div>
              <div className="table-wrap">
                <table className="result-table">
                  <thead>
                    <tr>
                      <th>位置</th>
                      <th>点位</th>
                      <th>芯片类型</th>
                      <th>左宽度</th>
                      <th>右宽度</th>
                      <th>左距离</th>
                      <th>右距离</th>
                      <th>目标浓度</th>
                      <th>复算浓度</th>
                      <th>绝对误差</th>
                    </tr>
                  </thead>
                  <tbody>
                    {task.result.chips.map((chip) => (
                      <tr key={chip.position}>
                        <td>{chip.position}</td>
                        <td>{chip.point_labels.join("/")}</td>
                        <td>{chip.chip_type}</td>
                        <td>{formatNumber(chip.left_width_mm, 3)}</td>
                        <td>{formatNumber(chip.right_width_mm, 3)}</td>
                        <td>{formatNumber(chip.left_distance_mm, 0)}</td>
                        <td>{formatNumber(chip.right_distance_mm, 0)}</td>
                        <td>{formatNumber(chip.target_concentration)}</td>
                        <td>{formatNumber(chip.predicted_concentration)}</td>
                        <td>{formatNumber(chip.absolute_error)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {task.result.notes.map((note) => (
                <p className="supporting-note" key={note}>
                  {note}
                </p>
              ))}
            </>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
