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

export const REVERSE_TASK_STORAGE_KEY = "drug-gradient-chip.reverse-task-id";

const TARGET_RANGE_WARNING =
  "目标浓度中包含超出推荐密集训练范围 [0.10, 0.95] 的数值，请谨慎评估结果。";
const LEGACY_TARGET_RANGE_WARNING =
  "Target concentrations include values outside the recommended dense training range [0.10, 0.95]; review the result carefully.";
const INTERNAL_SCREENING_NOTE =
  "内部筛选仅表示该结构已通过同一 Physics-GNN 代理模型的检查。";
const LEGACY_INTERNAL_SCREENING_NOTE =
  "Internal screening only means the structure was checked by the same Physics-GNN surrogate model.";
const CFD_NOTE = "最终设计仍需使用 Fluent/CFD 进行独立验证。";
const LEGACY_CFD_NOTE = "Final designs should still be independently verified with Fluent/CFD.";
const RECALCULATED_CONCENTRATION_NOTE =
  "反向设计中的复算浓度由反向优化所使用的内部代理模型生成，可能与独立正向预测结果存在轻微差异。";
const DEVICE_VARIATION_NOTE =
  "反向设计采用数值优化，不同计算设备可能得到不同但均满足代理模型筛选条件的设计方案。";

type InletMode = "inlet1" | "inlet2";

function formatNumber(value: number, digits = 6) {
  return Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function isRunningStatus(status: string | undefined) {
  return (
    status === "queued" ||
    status === "running" ||
    status === "preparing_model" ||
    status === "optimizing" ||
    status === "refining" ||
    status === "verifying"
  );
}

function isTerminalStatus(status: string | undefined) {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function statusText(status: string | undefined) {
  switch (status) {
    case "queued":
      return "等待运行";
    case "running":
      return "正在运行";
    case "preparing_model":
      return "正在准备模型";
    case "optimizing":
      return "正在优化结构";
    case "refining":
      return "正在细化结构";
    case "verifying":
      return "正在复算验证";
    case "completed":
      return "已完成";
    case "failed":
      return "运行失败";
    case "cancelled":
      return "已取消";
    default:
      return "未提交";
  }
}

function localizeReverseMessage(message: string) {
  if (message === LEGACY_TARGET_RANGE_WARNING) {
    return TARGET_RANGE_WARNING;
  }
  if (message === LEGACY_INTERNAL_SCREENING_NOTE) {
    return INTERNAL_SCREENING_NOTE;
  }
  if (message === LEGACY_CFD_NOTE) {
    return CFD_NOTE;
  }
  return message;
}

function getInletMode(form: ReverseDesignRequest): InletMode {
  return form.inlet1 === 1 ? "inlet1" : "inlet2";
}

export function ReversePage() {
  const [form, setForm] = useState<ReverseDesignRequest>(() => cloneDefaultReverseRequest());
  const [task, setTask] = useState<ReverseTaskStatusResponse | null>(null);
  const [error, setError] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const pollingRef = useRef<number | null>(null);

  const validationErrors = useMemo(() => validateReverseRequest(form), [form]);
  const isRunning = isRunningStatus(task?.status);
  const inletMode = getInletMode(form);

  useEffect(() => {
    const savedTaskId = window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY);
    if (!savedTaskId) {
      return;
    }

    let active = true;
    getReverseTask(savedTaskId)
      .then((savedTask) => {
        if (!active) {
          return;
        }
        setTask(savedTask);
        if (isTerminalStatus(savedTask.status)) {
          window.sessionStorage.removeItem(REVERSE_TASK_STORAGE_KEY);
        }
      })
      .catch((err) => {
        if (!active) {
          return;
        }
        if (err instanceof ApiClientError && err.kind === "reverse_not_found") {
          window.sessionStorage.removeItem(REVERSE_TASK_STORAGE_KEY);
          setTask(null);
          return;
        }
        setError(err instanceof Error ? err.message : "恢复反向任务失败。");
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isRunning || !task?.task_id) {
      return;
    }

    pollingRef.current = window.setInterval(async () => {
      try {
        const next = await getReverseTask(task.task_id);
        setTask(next);
        if (isTerminalStatus(next.status)) {
          window.sessionStorage.removeItem(REVERSE_TASK_STORAGE_KEY);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "轮询反向任务失败。");
      }
    }, 3000);

    return () => {
      if (pollingRef.current !== null) {
        window.clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [isRunning, task?.task_id]);

  function setInletMode(mode: InletMode) {
    setForm((current) => ({
      ...current,
      inlet1: mode === "inlet1" ? 1 : 0,
      inlet2: mode === "inlet2" ? 1 : 0,
    }));
  }

  function updateTarget(index: number, value: string) {
    const next = [...form.target_concentrations];
    next[index] = Number(value);
    setForm({ ...form, target_concentrations: next });
  }

  async function submit() {
    if (submitting || isRunning) {
      return;
    }
    setError("");
    if (validationErrors.length > 0) {
      setError(validationErrors[0]);
      return;
    }
    setSubmitting(true);
    try {
      const created = await createReverseTask(form);
      window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, created.task_id);
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
    if (!task?.task_id || cancelling) {
      return;
    }
    setError("");
    setCancelling(true);
    try {
      const cancelled = await cancelReverseTask(task.task_id);
      window.sessionStorage.removeItem(REVERSE_TASK_STORAGE_KEY);
      setTask(cancelled);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "取消反向设计任务失败。");
    } finally {
      setCancelling(false);
    }
  }

  function restoreExample() {
    setForm(cloneDefaultReverseRequest());
    setError("");
  }

  return (
    <section className="page-section">
      <div className="section-heading compact">
        <p className="eyebrow">芯片结构优化</p>
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
        <fieldset className="segmented reverse-inlet-selector" disabled={isRunning}>
          <legend>入口设置</legend>
          <span className="field-hint">选择高浓度入口</span>
          <label>
            <input
              type="radio"
              name="reverse-inlet"
              value="inlet1"
              checked={inletMode === "inlet1"}
              onChange={() => setInletMode("inlet1")}
            />
            Inlet1
          </label>
          <label>
            <input
              type="radio"
              name="reverse-inlet"
              value="inlet2"
              checked={inletMode === "inlet2"}
              onChange={() => setInletMode("inlet2")}
            />
            Inlet2
          </label>
        </fieldset>

        <div className="table-wrap reverse-target-wrap">
          <table className="input-table reverse-target-table">
            <colgroup>
              <col className="position-col" />
              <col className="point-col" />
              <col className="target-col" />
            </colgroup>
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
                    <input
                      className="reverse-target-input"
                      aria-label={`y${index + 1} 目标浓度`}
                      type="number"
                      step="0.01"
                      value={form.target_concentrations[index]}
                      disabled={isRunning}
                      onChange={(event) => updateTarget(index, event.target.value)}
                    />
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
            <button className="secondary" type="button" disabled={cancelling} onClick={cancel}>
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
              {localizeReverseMessage(warning)}
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
              <p className="supporting-note">{RECALCULATED_CONCENTRATION_NOTE}</p>
              <p className="supporting-note">{DEVICE_VARIATION_NOTE}</p>
              {task.result.notes.map((note) => (
                <p className="supporting-note" key={note}>
                  {localizeReverseMessage(note)}
                </p>
              ))}
            </>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
