import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiClientError,
  cancelReverseTask,
  createReverseTask,
  getReverseTask,
} from "../api/client";
import type { ApiErrorResponse, ReverseDesignRequest, ReverseTaskStatusResponse } from "../api/types";
import {
  REVERSE_TARGET_COUNT,
  cloneDefaultReverseRequest,
  validateReverseRequest,
} from "../domain/reverse";
import { apiClientErrorMessage, apiErrorCodeMessage } from "../i18n/errorMessages";
import type { I18nContextValue } from "../i18n/context";
import { useI18n } from "../i18n/useI18n";
import { usePageTitle } from "../i18n/usePageTitle";

export const REVERSE_TASK_STORAGE_KEY = "drug-gradient-chip.reverse-task-id";

const LEGACY_TARGET_RANGE_WARNING =
  "Target concentrations include values outside the recommended dense training range [0.10, 0.95]; review the result carefully.";
const LEGACY_INTERNAL_SCREENING_NOTE =
  "Internal screening only means the structure was checked by the same Physics-GNN surrogate model.";
const LEGACY_CFD_NOTE = "Final designs should still be independently verified with Fluent/CFD.";
const DENSE_TARGET_MIN = 0.1;
const DENSE_TARGET_MAX = 0.95;

type InletMode = "inlet1" | "inlet2";
type ReverseTaskStatus = NonNullable<ReverseTaskStatusResponse["status"]>;

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

function statusText(status: string | undefined, t: I18nContextValue["t"]) {
  switch (status) {
    case "queued":
    case "running":
    case "preparing_model":
    case "optimizing":
    case "refining":
    case "verifying":
    case "completed":
    case "failed":
    case "cancelled":
      return t(`status.${status}` as const);
    default:
      return t("status.idle");
  }
}

function localizeReverseMessage(message: string, t: I18nContextValue["t"]) {
  if (message === LEGACY_TARGET_RANGE_WARNING || message.includes("[0.10, 0.95]")) {
    return t("reverse.warningTargetRange");
  }
  if (message === LEGACY_INTERNAL_SCREENING_NOTE || message.includes("Physics-GNN surrogate model")) {
    return t("reverse.internalScreeningNote");
  }
  if (message === LEGACY_CFD_NOTE || message.includes("Fluent/CFD")) {
    return t("reverse.cfdNote");
  }
  return t("errors.reverse_failed");
}

function getInletMode(form: ReverseDesignRequest): InletMode {
  return form.inlet1 === 1 ? "inlet1" : "inlet2";
}

export function ReversePage() {
  const { t } = useI18n();
  usePageTitle("titles.reverse");
  const [form, setForm] = useState<ReverseDesignRequest>(() => cloneDefaultReverseRequest());
  const [task, setTask] = useState<ReverseTaskStatusResponse | null>(null);
  const [errorKind, setErrorKind] = useState<ApiClientError["kind"] | null>(null);
  const [fallbackErrorCode, setFallbackErrorCode] = useState<ApiErrorResponse["error"] | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const pollingRef = useRef<number | null>(null);

  const validationErrors = useMemo(() => validateReverseRequest(form, t), [form, t]);
  const hasTargetRangeWarning = form.target_concentrations.some(
    (value) => Number.isFinite(value) && (value < DENSE_TARGET_MIN || value > DENSE_TARGET_MAX),
  );
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
        setErrorKind(err instanceof ApiClientError ? err.kind : "unexpected");
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
        setErrorKind(err instanceof ApiClientError ? err.kind : "unexpected");
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
    setErrorKind(null);
    setFallbackErrorCode(undefined);
    if (validationErrors.length > 0) {
      setErrorKind("validation");
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
      setErrorKind(err instanceof ApiClientError ? err.kind : "unexpected");
    } finally {
      setSubmitting(false);
    }
  }

  async function cancel() {
    if (!task?.task_id || cancelling) {
      return;
    }
    setErrorKind(null);
    setFallbackErrorCode(undefined);
    setCancelling(true);
    try {
      const cancelled = await cancelReverseTask(task.task_id);
      window.sessionStorage.removeItem(REVERSE_TASK_STORAGE_KEY);
      setTask(cancelled);
    } catch (err) {
      setErrorKind(err instanceof ApiClientError ? err.kind : "unexpected");
    } finally {
      setCancelling(false);
    }
  }

  function restoreExample() {
    setForm(cloneDefaultReverseRequest());
    setErrorKind(null);
    setFallbackErrorCode(undefined);
  }

  const taskError = task?.error;

  return (
    <section className="page-section">
      <div className="section-heading compact">
        <p className="eyebrow">{t("reverse.eyebrow")}</p>
        <h1>{t("reverse.heading")}</h1>
        <p>{t("reverse.description")}</p>
      </div>

      <div className="status-banner ready">
        <span className="status-dot ready" />
        <span>{t("reverse.asyncStatus")}</span>
      </div>

      {errorKind ? (
        <div className="message error" role="alert">
          {apiClientErrorMessage(new ApiClientError(errorKind, ""), t)}
        </div>
      ) : null}
      {fallbackErrorCode ? (
        <div className="message error" role="alert">
          {apiErrorCodeMessage(fallbackErrorCode, t)}
        </div>
      ) : null}
      {validationErrors.length > 0 ? (
        <div className="message inline-warning">{validationErrors[0]}</div>
      ) : null}
      {!task && hasTargetRangeWarning ? (
        <div className="message inline-warning">{t("reverse.warningTargetRange")}</div>
      ) : null}

      <div className="tool-panel">
        <fieldset className="segmented reverse-inlet-selector" disabled={isRunning}>
          <legend>{t("common.inletSelection")}</legend>
          <span className="field-hint">{t("common.selectHighConcentrationInlet")}</span>
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
                <th>{t("common.position")}</th>
                <th>{t("common.point")}</th>
                <th>{t("common.targetConcentration")}</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: REVERSE_TARGET_COUNT }, (_, index) => (
                <tr key={index}>
                  <td>
                    {t("common.position")} {index + 1}
                  </td>
                  <td>y{index + 1}</td>
                  <td>
                    <input
                      className="reverse-target-input"
                      aria-label={`y${index + 1} ${t("common.targetConcentration")}`}
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
            {t("common.startReversePrediction")}
          </button>
          <button className="secondary" type="button" disabled={isRunning} onClick={restoreExample}>
            {t("common.restoreOfficialExample")}
          </button>
          {isRunning ? (
            <button className="secondary" type="button" disabled={cancelling} onClick={cancel}>
              {t("common.cancelTask")}
            </button>
          ) : null}
        </div>
      </div>

      {task ? (
        <section className="tool-panel results-panel">
          <div className="result-heading">
            <div>
              <h2>{t("reverse.taskStatus")}</h2>
              <p>
                {statusText(task.status as ReverseTaskStatus, t)}
                {task.elapsed_seconds
                  ? `, ${t("common.elapsed")} ${formatNumber(task.elapsed_seconds, 2)} ${t("common.seconds")}`
                  : ""}
              </p>
            </div>
          </div>
          {taskError ? <div className="message error">{apiErrorCodeMessage(taskError, t)}</div> : null}
          {task.warnings.map((warning) => (
            <div className="message inline-warning" key={warning}>
              {localizeReverseMessage(warning, t)}
            </div>
          ))}

          {task.result ? (
            <>
              <div className="metric-grid">
                <div>MAE: {formatNumber(task.result.metrics.mae)}</div>
                <div>RMSE: {formatNumber(task.result.metrics.rmse)}</div>
                <div>MaxAE: {formatNumber(task.result.metrics.maxae)}</div>
                <div>
                  {t("common.internalScreening")}:{" "}
                  {task.result.metrics.internal_screening_pass ? t("common.passed") : t("common.notPassed")}
                </div>
                <div>Spearman: {formatNumber(task.result.metrics.spearman)}</div>
                <div>
                  {t("reverse.selectedRestart")}: {task.result.metrics.selected_restart}
                </div>
              </div>
              <div className="table-wrap">
                <table className="result-table">
                  <thead>
                    <tr>
                      <th>{t("common.position")}</th>
                      <th>{t("common.point")}</th>
                      <th>{t("common.chipType")}</th>
                      <th>{t("common.leftWidth")}</th>
                      <th>{t("common.rightWidth")}</th>
                      <th>{t("reverse.bendClass")}</th>
                      <th>{t("reverse.leftDistance")}</th>
                      <th>{t("reverse.rightDistance")}</th>
                      <th>{t("common.targetConcentration")}</th>
                      <th>{t("common.surrogatePredictedConcentration")}</th>
                      <th>{t("common.absoluteError")}</th>
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
                        <td>
                          {chip.left_bend_class}/{chip.right_bend_class}
                        </td>
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
              <p className="supporting-note">{t("reverse.recalculatedNote")}</p>
              <p className="supporting-note">{t("reverse.deviceVariationNote")}</p>
              {task.result.notes.map((note) => (
                <p className="supporting-note" key={note}>
                  {localizeReverseMessage(note, t)}
                </p>
              ))}
            </>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
