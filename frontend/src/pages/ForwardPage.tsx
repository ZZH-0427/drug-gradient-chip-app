import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiClientError, getModelStatus, runForwardPrediction } from "../api/client";
import type { ForwardPredictionRequest, ForwardPredictionResponse, ModelStatusResponse } from "../api/types";
import {
  CHIP_COUNT_OPTIONS,
  CHIP_TYPE_OPTIONS,
  CURRENT_MODEL_CHIP_COUNT,
  MODEL_LIMIT_MESSAGE,
  cloneExampleForm,
  emptyEditableForm,
  resizeChipRows,
  type ChipFormRow,
  type ForwardFormState,
} from "../domain/forward";
import { validateForwardForm } from "../domain/validation";

type ModelStatusState =
  | { state: "checking" }
  | { state: "ready"; data: ModelStatusResponse }
  | { state: "unavailable"; message: string }
  | { state: "backend_offline"; message: string };

export function ForwardPage() {
  const [modelStatus, setModelStatus] = useState<ModelStatusState>({ state: "checking" });
  const [form, setForm] = useState<ForwardFormState>(() => cloneExampleForm());
  const [errors, setErrors] = useState<string[]>([]);
  const [pendingPayload, setPendingPayload] = useState<ForwardPredictionRequest | null>(null);
  const [result, setResult] = useState<ForwardPredictionResponse | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

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
          setModelStatus({ state: "backend_offline", message: error.message });
          return;
        }
        setModelStatus({
          state: "unavailable",
          message: "正向模型暂不可用，请检查模型资产和后端状态。",
        });
      });
    return () => {
      active = false;
    };
  }, []);

  const modelReady = modelStatus.state === "ready";
  const seedHeaders = result?.ensemble_seeds ?? [];

  function clearTransientState() {
    setErrors([]);
    setPendingPayload(null);
    setResult(null);
    setApiError(null);
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
    setApiError(null);
    const validation = validateForwardForm(form);
    setErrors(validation.errors);
    if (validation.payload) {
      setPendingPayload(validation.payload);
    }
  }

  async function submitPrediction() {
    if (!pendingPayload || isSubmitting) {
      return;
    }
    if (pendingPayload.chip_count !== CURRENT_MODEL_CHIP_COUNT) {
      setApiError(MODEL_LIMIT_MESSAGE);
      return;
    }
    setIsSubmitting(true);
    setApiError(null);
    try {
      const response = await runForwardPrediction(pendingPayload);
      setResult(response);
      setPendingPayload(null);
    } catch (error: unknown) {
      if (error instanceof ApiClientError) {
        setApiError(error.message);
      } else {
        setApiError("正向预测执行失败，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const statusLabel = useMemo(() => {
    if (modelStatus.state === "checking") {
      return "正在检查模型状态";
    }
    if (modelStatus.state === "ready") {
      return `模型已就绪，ensemble=${modelStatus.data.ensemble_size}`;
    }
    return modelStatus.message;
  }, [modelStatus]);

  return (
    <section className="page-section">
      <div className="section-heading compact">
        <p className="eyebrow">Forward prediction</p>
        <h1>正向预测</h1>
        <p>选择芯片数量并配置各位置参数。当前真实模型仅支持6个芯片。</p>
      </div>

      <div className={`status-banner ${modelReady ? "ready" : "blocked"}`} role="status">
        <strong>{modelReady ? "可运行" : "不可运行"}</strong>
        <span>{statusLabel}</span>
      </div>

      {apiError ? (
        <div className="message error" role="alert">
          {apiError}
        </div>
      ) : null}
      {errors.length > 0 ? (
        <div className="message error" role="alert">
          {errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
        </div>
      ) : null}

      {result ? (
        <ResultsView
          result={result}
          seedHeaders={seedHeaders}
          onBackToEdit={() => setResult(null)}
          onRerun={() => {
            const validation = validateForwardForm(form);
            if (validation.payload) {
              setPendingPayload(validation.payload);
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
      {isSubmitting ? <div className="loading-layer">正向模型处理中</div> : null}
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
          样本名称
          <input
            value={form.sample_name}
            disabled={disabled}
            required
            onChange={(event) => onSampleNameChange(event.target.value)}
          />
        </label>
        <label>
          芯片数量
          <select
            aria-label="芯片数量"
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
        <div className="chip-count-summary" aria-label="芯片数量摘要">
          <span>芯片数量：{form.chip_count}</span>
          <span>位置数量：{form.chips.length}</span>
          <span>点位数量：{form.chip_count * 2}</span>
        </div>
        <fieldset className="segmented" disabled={disabled}>
          <legend>入口设置</legend>
          <label>
            <input
              type="radio"
              name="inlet"
              checked={form.inletMode === "inlet1"}
              onChange={() => onInletModeChange("inlet1")}
            />
            inlet1=1, inlet2=0
          </label>
          <label>
            <input
              type="radio"
              name="inlet"
              checked={form.inletMode === "inlet2"}
              onChange={() => onInletModeChange("inlet2")}
            />
            inlet1=0, inlet2=1
          </label>
        </fieldset>
      </div>

      {!canPredict ? (
        <div className="message inline-warning" role="note">
          {MODEL_LIMIT_MESSAGE}
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="input-table">
          <thead>
            <tr>
              <th>位置</th>
              <th>点位</th>
              <th>芯片类型</th>
              <th>左宽度 mm</th>
              <th>右宽度 mm</th>
              <th>左弯曲直道距离 mm</th>
              <th>右弯曲直道距离 mm</th>
            </tr>
          </thead>
          <tbody>
            {form.chips.map((chip) => (
              <tr key={chip.position}>
                <td>位置 {chip.position}</td>
                <td>
                  {chip.point_left}/{chip.point_right}
                </td>
                <td>
                  <select
                    aria-label={`位置 ${chip.position} 芯片类型`}
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
                    label={`位置 ${chip.position} 左宽度`}
                    value={chip.left_width_mm}
                    disabled={disabled}
                    onChange={(value) => onChipChange(chip.position, "left_width_mm", value)}
                  />
                </td>
                <td>
                  <NumberInput
                    label={`位置 ${chip.position} 右宽度`}
                    value={chip.right_width_mm}
                    disabled={disabled}
                    onChange={(value) => onChipChange(chip.position, "right_width_mm", value)}
                  />
                </td>
                <td>
                  <NumberInput
                    label={`位置 ${chip.position} 左弯曲直道距离`}
                    value={chip.left_bend_straight_distance_mm}
                    disabled={disabled}
                    onChange={(value) =>
                      onChipChange(chip.position, "left_bend_straight_distance_mm", value)
                    }
                  />
                </td>
                <td>
                  <NumberInput
                    label={`位置 ${chip.position} 右弯曲直道距离`}
                    value={chip.right_bend_straight_distance_mm}
                    disabled={disabled}
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
          恢复示例
        </button>
        <button type="button" className="button secondary" disabled={disabled} onClick={onClear}>
          清空参数
        </button>
        <button type="submit" className="button primary" disabled={disabled || !modelReady}>
          确认参数
        </button>
      </div>
    </form>
  );
}

interface NumberInputProps {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}

function NumberInput({ label, value, disabled, onChange }: NumberInputProps) {
  return (
    <input
      aria-label={label}
      type="number"
      step="any"
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
  const canSubmit = payload.chip_count === CURRENT_MODEL_CHIP_COUNT;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="modal">
        <h2 id="confirm-title">确认正向预测参数</h2>
        <p>
          样本 {payload.sample_name}，{payload.inlet1 === 1 ? "inlet1=1, inlet2=0" : "inlet1=0, inlet2=1"}，
          共 {payload.chips.length} 个位置，{payload.chip_count * 2} 个点位。
        </p>
        {!canSubmit ? (
          <div className="message inline-warning" role="note">
            {MODEL_LIMIT_MESSAGE}
          </div>
        ) : null}
        <div className="action-row">
          <button type="button" className="button secondary" disabled={isSubmitting} onClick={onCancel}>
            返回编辑
          </button>
          <button type="button" className="button primary" disabled={isSubmitting || !canSubmit} onClick={onSubmit}>
            运行预测
          </button>
        </div>
      </div>
    </div>
  );
}

interface ResultsViewProps {
  result: ForwardPredictionResponse;
  seedHeaders: number[];
  onBackToEdit: () => void;
  onRerun: () => void;
}

function ResultsView({ result, seedHeaders, onBackToEdit, onRerun }: ResultsViewProps) {
  return (
    <div className="tool-panel">
      <div className="result-heading">
        <div>
          <h2>预测结果</h2>
          <p>样本：{result.sample_name}</p>
        </div>
        <div className="action-row">
          <button type="button" className="button secondary" onClick={onBackToEdit}>
            返回编辑
          </button>
          <button type="button" className="button primary" onClick={onRerun}>
            重新运行当前参数
          </button>
          <Link className="button secondary" to="/">
            返回首页
          </Link>
        </div>
      </div>
      <div className="table-wrap">
        <table className="result-table">
          <thead>
            <tr>
              <th>位置</th>
              <th>点位</th>
              <th>芯片类型</th>
              <th>mean</th>
              <th>std</th>
              {seedHeaders.map((seed) => (
                <th key={seed}>Seed {seed}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.predictions.map((item, index) => (
              <tr key={`${item.position}-${item.point}-${index}`}>
                <td>位置 {item.position || index + 1}</td>
                <td>{item.point}</td>
                <td>{item.chip_type}</td>
                <td>{formatNumber(item.mean)}</td>
                <td>{formatNumber(item.std)}</td>
                {seedHeaders.map((seed) => (
                  <td key={seed}>{formatNumber(item.seed_values[String(seed)])}</td>
                ))}
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
