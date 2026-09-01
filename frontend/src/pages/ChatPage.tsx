import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiClientError, getReverseTask, sendChatMessage } from "../api/client";
import type {
  ChatMessageResponse,
  ForwardPredictionResponse,
  ParameterSummary,
  ReverseTaskCreatedResponse,
  ReverseTaskStatusResponse,
} from "../api/types";
import { apiClientErrorMessage } from "../i18n/errorMessages";
import { useI18n } from "../i18n/useI18n";
import { usePageTitle } from "../i18n/usePageTitle";

type ChatRole = "user" | "assistant" | "system";

interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  structuredResponse?: ChatMessageResponse;
}

function isRunningStatus(status: string | undefined) {
  return status === "queued" || status === "running";
}

function isTerminalStatus(status: string | undefined) {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function formatNumber(value: number | undefined | null, digits = 6): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";
}

export function ChatPage() {
  const { locale, t } = useI18n();
  usePageTitle("assistant.heading");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentInput, setCurrentInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [currentResponse, setCurrentResponse] = useState<ChatMessageResponse | null>(null);
  const [reverseTask, setReverseTask] = useState<ReverseTaskStatusResponse | null>(null);
  const [apiErrorKind, setApiErrorKind] = useState<ApiClientError["kind"] | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const sendingRef = useRef(false);

  const reverseTaskId = reverseTask?.task_id ?? currentResponse?.reverse_task?.task_id;
  const reverseStatus = reverseTask?.status ?? currentResponse?.reverse_task?.status;

  useEffect(() => {
    if (!reverseTaskId || !isRunningStatus(reverseStatus)) {
      return;
    }
    let active = true;
    let timeoutId: number | undefined;

    const poll = async () => {
      try {
        const next = await getReverseTask(reverseTaskId);
        if (!active) {
          return;
        }
        setReverseTask(next);
        if (!isTerminalStatus(next.status) && isRunningStatus(next.status)) {
          timeoutId = window.setTimeout(() => {
            void poll();
          }, 3000);
        }
      } catch {
        if (active) {
          setApiErrorKind("reverse_failed");
        }
      }
    };

    timeoutId = window.setTimeout(() => {
      void poll();
    }, 3000);

    return () => {
      active = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [reverseStatus, reverseTaskId]);

  async function submitMessage(rawMessage?: string) {
    const text = (rawMessage ?? currentInput).trim();
    if (!text || sendingRef.current) {
      return;
    }
    sendingRef.current = true;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text,
    };
    setMessages((current) => [...current, userMessage]);
    setCurrentInput("");
    setSending(true);
    setApiErrorKind(null);
    try {
      const response = await sendChatMessage({
        session_id: sessionId,
        message: text,
        language: locale,
      });
      setSessionId(response.session_id);
      setCurrentResponse(response);
      setReverseTask((current) => nextReverseTaskForResponse(current, response));
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: response.error?.code === "AMBIGUOUS_INPUT" ? "system" : "assistant",
          text: response.assistant_message,
          structuredResponse: response,
        },
      ]);
    } catch (error: unknown) {
      setApiErrorKind(error instanceof ApiClientError ? error.kind : "unexpected");
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "system",
          text: t("assistant.genericError"),
        },
      ]);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    void submitMessage();
  }

  function runThroughChat() {
    void submitMessage(locale === "zh-CN" ? "\u8fd0\u884c" : "run");
  }

  function cancelReverseThroughChat() {
    void submitMessage(locale === "zh-CN" ? "\u53d6\u6d88" : "cancel");
  }

  function focusComposer() {
    inputRef.current?.focus();
  }

  const lastForwardResult = currentResponse?.forward_prediction ?? null;

  return (
    <section className="page-section chat-page">
      <div className="section-heading compact">
        <p className="eyebrow">{t("assistant.eyebrow")}</p>
        <h1>{t("assistant.heading")}</h1>
        <p>{t("assistant.intro")}</p>
      </div>

      {apiErrorKind ? (
        <div className="message error" role="alert">
          {apiClientErrorMessage(new ApiClientError(apiErrorKind, ""), t)}
        </div>
      ) : null}

      <div className="chat-layout">
        <div className="tool-panel chat-panel">
          <div className="chat-messages" aria-label={t("assistant.messages")}>
            <WelcomeBlock />
            {messages.map((message) => (
              <article
                className={`chat-message chat-message-${message.role}`}
                key={message.id}
              >
                <p>{message.text}</p>
                {message.structuredResponse?.error?.code === "AMBIGUOUS_INPUT" ? (
                  <span className="chat-clarification">{t("assistant.clarification")}</span>
                ) : null}
              </article>
            ))}
            {sending ? (
              <article className="chat-message chat-message-assistant">
                <p>{t("assistant.sending")}</p>
              </article>
            ) : null}
          </div>

          <div className="chat-composer">
            <textarea
              ref={inputRef}
              aria-label={t("assistant.inputLabel")}
              placeholder={t("assistant.placeholder")}
              value={currentInput}
              disabled={sending}
              rows={3}
              onChange={(event) => setCurrentInput(event.target.value)}
              onKeyDown={handleComposerKeyDown}
            />
            <button
              className="primary"
              type="button"
              disabled={sending || !currentInput.trim()}
              onClick={() => void submitMessage()}
            >
              {sending ? t("assistant.sending") : t("assistant.send")}
            </button>
          </div>
        </div>

        <aside className="chat-side">
          {currentResponse?.parameter_summary ? (
            <ParameterSummaryCard summary={currentResponse.parameter_summary} />
          ) : null}
          {currentResponse?.confirmation || currentResponse?.state === "ready_for_confirmation" ? (
            <ConfirmationCard
              response={currentResponse}
              sending={sending}
              onRun={runThroughChat}
              onContinue={focusComposer}
            />
          ) : null}
          {lastForwardResult ? <ForwardResultCard result={lastForwardResult} /> : null}
          {reverseTask || currentResponse?.reverse_task ? (
            <ReverseTaskCard
              task={reverseTask}
              created={currentResponse?.reverse_task ?? null}
              sending={sending}
              onCancel={cancelReverseThroughChat}
            />
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function WelcomeBlock() {
  const { t } = useI18n();
  return (
    <article className="chat-message chat-message-assistant">
      <p>{t("assistant.welcome")}</p>
      <div className="chat-examples" aria-label={t("assistant.examples")}>
        <span>{t("assistant.exampleForward")}</span>
        <span>{t("assistant.exampleInlet")}</span>
        <span>{t("assistant.exampleReverse")}</span>
      </div>
    </article>
  );
}

function ParameterSummaryCard({
  summary,
  embedded = false,
}: {
  summary: ParameterSummary;
  embedded?: boolean;
}) {
  const { t } = useI18n();
  const chips = Array.isArray(summary.chips) ? summary.chips : [];
  const targets = Array.isArray(summary.target_concentrations) ? summary.target_concentrations : [];
  const missing = Array.isArray(summary.missing_fields) ? summary.missing_fields : [];
  const targetPositions = reverseTargetPositions(summary, targets);
  const isReverseSummary = (targetPositions.length > 0 || summary.target_position_count === 6) && chips.length === 0;
  if (isReverseSummary) {
    return (
      <section
        className={embedded ? "chat-parameter-card embedded" : "chat-parameter-card tool-panel"}
        aria-label={t("assistant.parameterSummary")}
      >
        <h2>{t("assistant.parameterSummary")}</h2>
        <dl className="summary-list">
          <div>
            <dt>{t("common.inletSelection")}</dt>
            <dd>{reverseInletSummary(summary)}</dd>
          </div>
          <div>
            <dt>{t("assistant.reverseTargetPositionCount")}</dt>
            <dd>{t("assistant.fixedSixTargetPositions")}</dd>
          </div>
        </dl>
        <div className="table-wrap">
          <table className="compact-table">
            <thead>
              <tr>
                <th>{t("common.position")}</th>
                <th>{t("common.targetConcentration")}</th>
              </tr>
            </thead>
            <tbody>
              {targetPositions.map((target, index) => (
                <tr key={String(target.position ?? index + 1)}>
                  <td>{displayValue(target.position ?? index + 1)}</td>
                  <td>{displayValue(target.target_concentration)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {missing.length > 0 ? (
          <div className="missing-list">
            <strong>{t("assistant.missingParameters")}</strong>
            <ul>
              {missing.map((field) => (
                <li key={String(field)}>{String(field)}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>
    );
  }
  return (
    <section
      className={embedded ? "chat-parameter-card embedded" : "chat-parameter-card tool-panel"}
      aria-label={t("assistant.parameterSummary")}
    >
      <h2>{t("assistant.parameterSummary")}</h2>
      <dl className="summary-list">
        <div>
          <dt>{t("common.sampleName")}</dt>
          <dd>{displayValue(summary.sample_name)}</dd>
        </div>
        <div>
          <dt>{t("common.numberOfChips")}</dt>
          <dd>{displayValue(summary.chip_count)}</dd>
        </div>
        <div>
          <dt>{t("common.inletSelection")}</dt>
          <dd>
            {summary.inlet1 === undefined && summary.inlet2 === undefined
              ? t("assistant.notSet")
              : `Inlet1=${displayValue(summary.inlet1)}, Inlet2=${displayValue(summary.inlet2)}`}
          </dd>
        </div>
      </dl>
      {chips.length > 0 ? (
        <div className="table-wrap">
          <table className="compact-table">
            <thead>
              <tr>
                <th>{t("common.position")}</th>
                <th>{t("common.chipType")}</th>
                <th>{t("common.leftWidth")}</th>
                <th>{t("common.rightWidth")}</th>
                <th>{t("common.leftBendDistance")}</th>
                <th>{t("common.rightBendDistance")}</th>
              </tr>
            </thead>
            <tbody>
              {chips.map((item, index) => {
                const chip = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
                return (
                  <tr key={String(chip.position ?? index)}>
                    <td>{displayValue(chip.position)}</td>
                    <td>{displayValue(chip.chip_type)}</td>
                    <td>{displayValue(chip.left_width_mm)}</td>
                    <td>{displayValue(chip.right_width_mm)}</td>
                    <td>{displayValue(chip.left_bend_straight_distance_mm)}</td>
                    <td>{displayValue(chip.right_bend_straight_distance_mm)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {targets.length > 0 ? (
        <p>
          {t("common.targetConcentration")}: {targets.map(displayValue).join(", ")}
        </p>
      ) : null}
      {missing.length > 0 ? (
        <div className="missing-list">
          <strong>{t("assistant.missingParameters")}</strong>
          <ul>
            {missing.map((field) => (
              <li key={String(field)}>{String(field)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function reverseInletSummary(summary: ParameterSummary): string {
  if (summary.inlet1 === undefined && summary.inlet2 === undefined) {
    return "—";
  }
  return `Inlet1=${displayValue(summary.inlet1)}, Inlet2=${displayValue(summary.inlet2)}`;
}

function reverseTargetPositions(summary: ParameterSummary, targets: unknown[]) {
  if (Array.isArray(summary.target_positions)) {
    return summary.target_positions
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
      .map((item, index) => ({
        position: item.position ?? index + 1,
        target_concentration: item.target_concentration,
      }));
  }
  return targets.map((target, index) => ({
    position: index + 1,
    target_concentration: target,
  }));
}

function ConfirmationCard({
  response,
  sending,
  onRun,
  onContinue,
}: {
  response: ChatMessageResponse;
  sending: boolean;
  onRun: () => void;
  onContinue: () => void;
}) {
  const { t } = useI18n();
  const mode = response.confirmation?.mode;
  return (
    <section className="chat-confirmation-card tool-panel">
      <h2>{mode === "reverse" ? t("assistant.confirmReverse") : t("assistant.confirmForward")}</h2>
      {response.confirmation ? <ParameterSummaryCard summary={response.confirmation.summary} embedded /> : null}
      <div className="action-row">
        <button className="primary" type="button" disabled={sending} onClick={onRun}>
          {mode === "reverse" ? t("assistant.runReverse") : t("assistant.runPrediction")}
        </button>
        <button className="secondary" type="button" disabled={sending} onClick={onContinue}>
          {t("assistant.continueEditing")}
        </button>
      </div>
    </section>
  );
}

function ForwardResultCard({ result }: { result: ForwardPredictionResponse }) {
  const { t } = useI18n();
  return (
    <section className="chat-result-card tool-panel">
      <h2>{t("assistant.forwardResult")}</h2>
      <p>{t("forward.resultSample", { sample: result.sample_name })}</p>
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
            {result.predictions.map((item) => (
              <tr key={`${item.position}-${item.point}`}>
                <td>{item.position}</td>
                <td>{item.point}</td>
                <td>{item.chip_type}</td>
                <td>{formatNumber(item.concentration)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ReverseTaskCard({
  task,
  created,
  sending,
  onCancel,
}: {
  task: ReverseTaskStatusResponse | null;
  created: ReverseTaskCreatedResponse | null;
  sending: boolean;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const status = task?.status ?? created?.status;
  const taskId = task?.task_id ?? created?.task_id;
  const result = task?.result;
  return (
    <section className="chat-result-card tool-panel">
      <h2>{t("assistant.reverseTask")}</h2>
      <p>
        {taskId ? `${t("assistant.taskId")}: ${taskId}` : ""}
        {taskId ? ", " : ""}
        {t("assistant.status")}: {status ? t(`status.${status}`) : t("status.idle")}
      </p>
      {isRunningStatus(status) ? (
        <button className="secondary" type="button" disabled={sending} onClick={onCancel}>
          {t("assistant.cancelTask")}
        </button>
      ) : null}
      {task?.error ? <div className="message error">{task.error.message}</div> : null}
      {result ? (
        <>
          <div className="metric-grid">
            <div>MAE: {formatNumber(result.metrics.mae)}</div>
            <div>RMSE: {formatNumber(result.metrics.rmse)}</div>
            <div>MaxAE: {formatNumber(result.metrics.maxae)}</div>
            <div>Spearman: {formatNumber(result.metrics.spearman)}</div>
          </div>
          <div className="table-wrap">
            <table className="result-table">
              <thead>
                <tr>
                  <th>{t("common.position")}</th>
                  <th>{t("common.chipType")}</th>
                  <th>{t("common.targetConcentration")}</th>
                  <th>{t("common.surrogatePredictedConcentration")}</th>
                  <th>{t("common.absoluteError")}</th>
                </tr>
              </thead>
              <tbody>
                {result.chips.map((chip) => (
                  <tr key={chip.position}>
                    <td>{chip.position}</td>
                    <td>{chip.chip_type}</td>
                    <td>{formatNumber(chip.target_concentration)}</td>
                    <td>{formatNumber(chip.predicted_concentration)}</td>
                    <td>{formatNumber(chip.absolute_error)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.notes.map((note) => (
            <p className="supporting-note" key={note}>
              {note}
            </p>
          ))}
        </>
      ) : null}
    </section>
  );
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "-";
  }
  return String(value);
}

function nextReverseTaskForResponse(
  current: ReverseTaskStatusResponse | null,
  response: ChatMessageResponse,
): ReverseTaskStatusResponse | null {
  if (response.reverse_task) {
    return {
      task_id: response.reverse_task.task_id,
      status: response.reverse_task.status,
      created_at: new Date().toISOString(),
      warnings: [],
    };
  }
  if (
    response.forward_prediction ||
    response.confirmation?.mode === "forward" ||
    response.intent === "start_forward"
  ) {
    return null;
  }
  if (response.confirmation?.mode === "reverse" || response.intent === "start_reverse") {
    return current && isRunningStatus(current.status) ? current : null;
  }
  return current;
}
