import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiClientError, getModelStatus, runForwardPrediction } from "../api/client";
import type { ForwardPredictionRequest, ForwardPredictionResponse, ModelStatusResponse } from "../api/types";
import {
  CHIP_COUNT_OPTIONS,
  CHIP_TYPE_OPTIONS,
  CURRENT_MODEL_CHIP_COUNT,
  FORWARD_DISTANCE_STEP,
  FORWARD_WIDTH_MAX,
  FORWARD_WIDTH_MIN,
  FORWARD_WIDTH_STEP,
  cloneExampleForm,
  emptyEditableForm,
  resizeChipRows,
  type ChipFormRow,
  type ForwardFormState,
} from "../domain/forward";
import { validateForwardForm } from "../domain/validation";
import { apiClientErrorMessage } from "../i18n/errorMessages";
import { useI18n } from "../i18n/useI18n";
import { usePageTitle } from "../i18n/usePageTitle";

type ModelStatusState =
  | { state: "checking" }
  | { state: "ready"; data: ModelStatusResponse }
  | { state: "unavailable" }
  | { state: "backend_offline" };

export function ForwardPage() {
  const { t } = useI18n();
  usePageTitle("titles.forward");
  const [modelStatus, setModelStatus] = useState<ModelStatusState>({ state: "checking" });
  const [form, setForm] = useState<ForwardFormState>(() => cloneExampleForm());
  const [showValidationErrors, setShowValidationErrors] = useState(false);
  const [pendingPayload, setPendingPayload] = useState<ForwardPredictionRequest | null>(null);
  const [result, setResult] = useState<ForwardPredictionResponse | null>(null);
  const [apiErrorKind, setApiErrorKind] = useState<ApiClientError["kind"] | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validation = useMemo(() => validateForwardForm(form, t), [form, t]);

  useEffect(() => {
    let active = true;
    setModelStatus({ state: "checking" });
    getModelStatus()
      .then((data) => {
        if (active) {
          setModelStatus({ state: "ready", data });
        }
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        if (error instanceof ApiClientError && error.kind === "network") {
          setModelStatus({ state: "backend_offline" });
          return;
        }
        setModelStatus({ state: "unavailable" });
      });
    return () => {
      active = false;
    };
  }, []);

  const modelReady = modelStatus.state === "ready";

  function clearTransientState() {
    setShowValidationErrors(false);
    setPendingPayload(null);
    setResult(null);
    setApiErrorKind(null);
    setIsSubmitting(false);
  }

  function updateChipCount(chipCount: number) {
    setForm((current) => ({
      ...current,
      chip_count: chipCount,
      chips: resizeChipRows(current.chips, chipCount),
    }));
    clearTransientState();
  }

  function updateChip(position: number, field: keyof ChipFormRow, value: string) {
    setForm((current) => ({
      ...current,
      chips: current.chips.map((chip) =>
        chip.position === position ? { ...chip, [field]: value } : chip,
      ),
    }));
  }

  function confirmParameters() {
    setApiErrorKind(null);
    setShowValidationErrors(validation.errors.length > 0);
    if (validation.payload) {
      setPendingPayload(validation.payload);
    }
  }

  async function submitPrediction() {
    if (!pendingPayload || isSubmitting) {
      return;
    }
    if (pendingPayload.chip_count !== CURRENT_MODEL_CHIP_COUNT) {
      setApiErrorKind("unsupported_chip_count");
      return;
    }
    setIsSubmitting(true);
    setApiErrorKind(null);
    try {
      const response = await runForwardPrediction(pendingPayload);
      setResult(response);
      setPendingPayload(null);
    } catch (error: unknown) {
      setApiErrorKind(error instanceof ApiClientError ? error.kind : "inference_failure");
    } finally {
      setIsSubmitting(false);
    }
  }

  const statusLabel = useMemo(() => {
    if (modelStatus.state === "checking") {
      return t("forward.modelChecking");
    }
    if (modelStatus.state === "ready") {
      return t("forward.modelReady", { output: modelStatus.data.public_output });
    }
    if (modelStatus.state === "backend_offline") {
      return t("errors.network");
    }
    return t("forward.modelUnavailable");
  }, [modelStatus, t]);

  return (
    <section className="page-section">
      <div className="section-heading compact">
        <p className="eyebrow">{t("forward.eyebrow")}</p>
        <h1>{t("forward.heading")}</h1>
        <p>{t("forward.description")}</p>
      </div>

      <div className={`status-banner ${modelReady ? "ready" : "blocked"}`} role="status">
        <strong>{modelReady ? t("common.ready") : t("common.unavailable")}</strong>
        <span>{statusLabel}</span>
      </div>

      {apiErrorKind ? (
        <div className="message error" role="alert">
          {apiClientErrorMessage(new ApiClientError(apiErrorKind, ""), t)}
        </div>
      ) : null}
      {showValidationErrors && validation.errors.length > 0 ? (
        <div className="message error" role="alert">
          {validation.errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      ) : null}

      {result ? (
        <ResultsView
          result={result}
          onBackToEdit={() => setResult(null)}
          onRerun={() => {
            const nextValidation = validateForwardForm(form, t);
            if (nextValidation.payload) {
              setPendingPayload(nextValidation.payload);
            }
          }}
        />
      ) : (
        <FormView
          form={form}
          disabled={isSubmitting}
          modelReady={modelReady}
          onChipCountChange={updateChipCount}
          onSampleNameChange={(value) => setForm((current) => ({ ...current, sample_name: value }))}
          onInletModeChange={(value) => setForm((current) => ({ ...current, inletMode: value }))}
          onChipChange={updateChip}
          onRestoreExample={() => {
            setForm(cloneExampleForm());
            clearTransientState();
          }}
          onClear={() => {
            setForm((current) => emptyEditableForm(current));
            clearTransientState();
          }}
          onConfirm={confirmParameters}
        />
      )}

      {pendingPayload ? (
        <ConfirmDialog
          payload={pendingPayload}
          isSubmitting={isSubmitting}
          onCancel={() => setPendingPayload(null)}
          onSubmit={submitPrediction}
        />
      ) : null}
      {isSubmitting ? <div className="loading-layer">{t("forward.loading")}</div> : null}
    </section>
  );
}

interface FormViewProps {
  form: ForwardFormState;
  disabled: boolean;
  modelReady: boolean;
  onChipCountChange: (value: number) => void;
  onSampleNameChange: (value: string) => void;
  onInletModeChange: (value: "inlet1" | "inlet2") => void;
  onChipChange: (position: number, field: keyof ChipFormRow, value: string) => void;
  onRestoreExample: () => void;
  onClear: () => void;
  onConfirm: () => void;
}

function FormView({
  form,
  disabled,
  modelReady,
  onChipCountChange,
  onSampleNameChange,
  onInletModeChange,
  onChipChange,
  onRestoreExample,
  onClear,
  onConfirm,
}: FormViewProps) {
  const { t } = useI18n();
  const canPredict = form.chip_count === CURRENT_MODEL_CHIP_COUNT;
  return (
    <form
      className="tool-panel"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onConfirm();
      }}
    >
      <div className="form-grid form-grid-wide">
        <label>
          {t("common.sampleName")}
          <input
            value={form.sample_name}
            disabled={disabled}
            required
            onChange={(event) => onSampleNameChange(event.target.value)}
          />
        </label>
        <label>
          {t("common.numberOfChips")}
          <select
            aria-label={t("common.numberOfChips")}
            value={form.chip_count}
            disabled={disabled}
            onChange={(event) => onChipCountChange(Number(event.target.value))}
          >
            {CHIP_COUNT_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <div className="chip-count-summary" aria-label={t("forward.chipCountSummary")}>
          <span>{t("forward.chipSummary", { count: form.chip_count })}</span>
          <span>{t("forward.positionSummary", { count: form.chips.length })}</span>
          <span>{t("forward.pointSummary", { count: form.chip_count * 2 })}</span>
        </div>
        <fieldset className="segmented" disabled={disabled}>
          <legend>{t("common.inletSelection")}</legend>
          <label>
            <input
              type="radio"
              name="inlet"
              checked={form.inletMode === "inlet1"}
              onChange={() => onInletModeChange("inlet1")}
            />
            Inlet1=1, Inlet2=0
          </label>
          <label>
            <input
              type="radio"
              name="inlet"
              checked={form.inletMode === "inlet2"}
              onChange={() => onInletModeChange("inlet2")}
            />
            Inlet1=0, Inlet2=1
          </label>
        </fieldset>
      </div>

      {!canPredict ? (
        <div className="message inline-warning" role="note">
          {t("forward.modelLimit")}
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="input-table">
          <thead>
            <tr>
              <th>{t("common.position")}</th>
              <th>{t("common.point")}</th>
              <th>{t("common.chipType")}</th>
              <th>{t("common.leftWidth")} mm</th>
              <th>{t("common.rightWidth")} mm</th>
              <th>{t("common.leftBendDistance")} mm</th>
              <th>{t("common.rightBendDistance")} mm</th>
            </tr>
          </thead>
          <tbody>
            {form.chips.map((chip) => (
              <tr key={chip.position}>
                <td>
                  {t("common.position")} {chip.position}
                </td>
                <td>
                  {chip.point_left}/{chip.point_right}
                </td>
                <td>
                  <select
                    aria-label={`${t("common.position")} ${chip.position} ${t("common.chipType")}`}
                    value={chip.chip_type}
                    disabled={disabled}
                    onChange={(event) => onChipChange(chip.position, "chip_type", event.target.value)}
                  >
                    {CHIP_TYPE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <NumberInput
                    label={`${t("common.position")} ${chip.position} ${t("common.leftWidth")}`}
                    value={chip.left_width_mm}
                    disabled={disabled}
                    min={FORWARD_WIDTH_MIN}
                    max={FORWARD_WIDTH_MAX}
                    step={FORWARD_WIDTH_STEP}
                    onChange={(value) => onChipChange(chip.position, "left_width_mm", value)}
                  />
                </td>
                <td>
                  <NumberInput
                    label={`${t("common.position")} ${chip.position} ${t("common.rightWidth")}`}
                    value={chip.right_width_mm}
                    disabled={disabled}
                    min={FORWARD_WIDTH_MIN}
                    max={FORWARD_WIDTH_MAX}
                    step={FORWARD_WIDTH_STEP}
                    onChange={(value) => onChipChange(chip.position, "right_width_mm", value)}
                  />
                </td>
                <td>
                  <NumberInput
                    label={`${t("common.position")} ${chip.position} ${t("common.leftBendDistance")}`}
                    value={chip.left_bend_straight_distance_mm}
                    disabled={disabled}
                    step={FORWARD_DISTANCE_STEP}
                    onChange={(value) =>
                      onChipChange(chip.position, "left_bend_straight_distance_mm", value)
                    }
                  />
                </td>
                <td>
                  <NumberInput
                    label={`${t("common.position")} ${chip.position} ${t("common.rightBendDistance")}`}
                    value={chip.right_bend_straight_distance_mm}
                    disabled={disabled}
                    step={FORWARD_DISTANCE_STEP}
                    onChange={(value) =>
                      onChipChange(chip.position, "right_bend_straight_distance_mm", value)
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="action-row">
        <button type="button" className="button secondary" disabled={disabled} onClick={onRestoreExample}>
          {t("common.restoreOfficialExample")}
        </button>
        <button type="button" className="button secondary" disabled={disabled} onClick={onClear}>
          {t("common.clear")}
        </button>
        <button type="submit" className="button primary" disabled={disabled || !modelReady}>
          {t("common.confirmInputs")}
        </button>
      </div>
    </form>
  );
}

interface NumberInputProps {
  label: string;
  value: string;
  disabled: boolean;
  min?: number;
  max?: number;
  step: number;
  onChange: (value: string) => void;
}

function NumberInput({ label, value, disabled, min, max, step, onChange }: NumberInputProps) {
  return (
    <input
      aria-label={label}
      type="number"
      min={min}
      max={max}
      step={step}
      required
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

interface ConfirmDialogProps {
  payload: ForwardPredictionRequest;
  isSubmitting: boolean;
  onCancel: () => void;
  onSubmit: () => void;
}

function ConfirmDialog({ payload, isSubmitting, onCancel, onSubmit }: ConfirmDialogProps) {
  const { t } = useI18n();
  const canSubmit = payload.chip_count === CURRENT_MODEL_CHIP_COUNT;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="modal">
        <h2 id="confirm-title">{t("forward.confirmTitle")}</h2>
        <p>
          {t("forward.confirmSummary", {
            sample: payload.sample_name,
            inlet: payload.inlet1 === 1 ? "Inlet1=1, Inlet2=0" : "Inlet1=0, Inlet2=1",
            positions: payload.chips.length,
            points: payload.chip_count * 2,
          })}
        </p>
        {!canSubmit ? (
          <div className="message inline-warning" role="note">
            {t("forward.modelLimit")}
          </div>
        ) : null}
        <div className="action-row">
          <button type="button" className="button secondary" disabled={isSubmitting} onClick={onCancel}>
            {t("common.backToEdit")}
          </button>
          <button type="button" className="button primary" disabled={isSubmitting || !canSubmit} onClick={onSubmit}>
            {t("common.runPrediction")}
          </button>
        </div>
      </div>
    </div>
  );
}

interface ResultsViewProps {
  result: ForwardPredictionResponse;
  onBackToEdit: () => void;
  onRerun: () => void;
}

function ResultsView({ result, onBackToEdit, onRerun }: ResultsViewProps) {
  const { t } = useI18n();
  return (
    <div className="tool-panel">
      <div className="result-heading">
        <div>
          <h2>{t("forward.resultTitle")}</h2>
          <p>{t("forward.resultSample", { sample: result.sample_name })}</p>
        </div>
        <div className="action-row">
          <button type="button" className="button secondary" onClick={onBackToEdit}>
            {t("common.backToEdit")}
          </button>
          <button type="button" className="button primary" onClick={onRerun}>
            {t("forward.rerunCurrent")}
          </button>
          <Link className="button secondary" to="/">
            {t("common.backToHome")}
          </Link>
        </div>
      </div>
      <div className="table-wrap">
        <table className="result-table">
          <thead>
            <tr>
              <th>{t("common.position")}</th>
              <th>{t("common.point")}</th>
              <th>{t("common.chipType")}</th>
              <th>{t("common.predictedConcentration")}</th>
            </tr>
          </thead>
          <tbody>
            {result.predictions.map((item, index) => (
              <tr key={`${item.position}-${item.point}-${index}`}>
                <td>
                  {t("common.position")} {item.position || index + 1}
                </td>
                <td>{item.point}</td>
                <td>{item.chip_type}</td>
                <td>{formatNumber(item.concentration)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatNumber(value: number | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(6) : "-";
}
