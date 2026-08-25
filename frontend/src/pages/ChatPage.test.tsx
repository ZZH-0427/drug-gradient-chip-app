import { act } from "react";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ChatMessageResponse } from "../api/types";
import { LOCALE_STORAGE_KEY } from "../i18n/locale";
import { LanguageSwitcher } from "../i18n/LanguageSwitcher";
import { renderWithI18n } from "../test/renderWithI18n";
import { ChatPage } from "./ChatPage";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Assistant route and initial state", () => {
  it("renders the Assistant route and keeps Forward and Reverse routes available", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    renderWithI18n(
      <MemoryRouter initialEntries={["/assistant"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Conversational Predictor" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Forward Prediction" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reverse Prediction" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Conversational Predictor" })).toBeInTheDocument();
  });

  it("shows local welcome examples without creating a backend session", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    const fetchMock = mockFetch();

    renderChatPage();

    expect(screen.getByText("You can configure forward or reverse prediction parameters through conversation.")).toBeInTheDocument();
    expect(screen.getByText("use 6 chips for forward prediction")).toBeInTheDocument();
    expect(screen.getByText("inlet 1 high")).toBeInTheDocument();
    expect(screen.getByText("start reverse prediction")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("Assistant chat sending", () => {
  it("sends the first request without session_id and reuses returned session_id afterward", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(chatResponse({ session_id: "session-1", assistant_message: "Recorded one." })),
      jsonResponse(chatResponse({ session_id: "session-1", assistant_message: "Recorded two." })),
    );
    renderChatPage();

    await sendMessage(user, "use 6 chips for forward prediction");
    await screen.findByText("Recorded one.");
    await sendMessage(user, "inlet 1 high");
    await screen.findByText("Recorded two.");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestBody(fetchMock, 0)).toMatchObject({
      message: "use 6 chips for forward prediction",
      language: "en",
      session_id: null,
    });
    expect(requestBody(fetchMock, 1)).toMatchObject({
      message: "inlet 1 high",
      language: "en",
      session_id: "session-1",
    });
  });

  it("disables Send while loading and prevents duplicate requests", async () => {
    const user = userEvent.setup();
    let resolveChat: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolveChat = resolve;
    });
    const fetchMock = mockFetch(pending);
    renderChatPage();

    await user.type(messageBox(), "use 6 chips for forward prediction");
    const send = screen.getByRole("button", { name: "Send" });
    await user.click(send);
    await user.click(send);

    expect(send).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveChat(jsonResponse(chatResponse({ assistant_message: "Recorded." })));
    expect(await screen.findByText("Recorded.")).toBeInTheDocument();
  });

  it("blocks same-tick rapid Send requests with one synchronous lock", async () => {
    let resolveChat: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolveChat = resolve;
    });
    const fetchMock = mockFetch(pending);
    renderChatPage();

    fireEvent.change(messageBox(), { target: { value: "use 6 chips for forward prediction" } });
    const send = screen.getByRole("button", { name: "Send" });
    fireEvent.click(send);
    fireEvent.click(send);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveChat(jsonResponse(chatResponse({ assistant_message: "Recorded." })));
    expect(await screen.findByText("Recorded.")).toBeInTheDocument();
  });

  it("blocks same-tick rapid Enter submissions with one synchronous lock", async () => {
    let resolveChat: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      resolveChat = resolve;
    });
    const fetchMock = mockFetch(pending);
    renderChatPage();

    fireEvent.change(messageBox(), { target: { value: "use 6 chips for forward prediction" } });
    fireEvent.keyDown(messageBox(), { key: "Enter", code: "Enter" });
    fireEvent.keyDown(messageBox(), { key: "Enter", code: "Enter" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveChat(jsonResponse(chatResponse({ assistant_message: "Recorded." })));
    expect(await screen.findByText("Recorded.")).toBeInTheDocument();
  });

  it("submits with Enter and keeps Shift+Enter as a line break", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(chatResponse({ assistant_message: "Recorded." })));
    renderChatPage();

    await user.type(messageBox(), "line one{Shift>}{Enter}{/Shift}line two");
    expect(messageBox()).toHaveValue("line one\nline two");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("Recorded.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not submit while IME composition is confirming text with Enter", async () => {
    const fetchMock = mockFetch(jsonResponse(chatResponse({ assistant_message: "Recorded." })));
    renderChatPage();

    fireEvent.change(messageBox(), { target: { value: "use 6 chips" } });
    const composingEnter = new KeyboardEvent("keydown", {
      key: "Enter",
      code: "Enter",
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(composingEnter, "isComposing", { value: true });
    fireEvent(messageBox(), composingEnter);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(composingEnter.defaultPrevented).toBe(false);

    fireEvent.keyDown(messageBox(), { key: "Enter", code: "Enter", isComposing: false });

    expect(await screen.findByText("Recorded.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves session_id when switching language inside the page", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(chatResponse({ session_id: "session-1", assistant_message: "Recorded." })),
      jsonResponse(chatResponse({ session_id: "session-1", assistant_message: "Language recorded." })),
    );
    renderChatPage({ withLanguageSwitcher: true });

    await sendMessage(user, "use 6 chips for forward prediction");
    await screen.findByText("Recorded.");
    await user.click(screen.getByRole("button", { name: /中文|涓枃/ }));
    await sendMessage(user, "inlet 1 high");

    await screen.findByText("Language recorded.");
    expect(requestBody(fetchMock, 1)).toMatchObject({
      session_id: "session-1",
      language: "zh-CN",
    });
  });
});

describe("Assistant structured cards", () => {
  it("renders parameter summary and missing fields without fake values", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(
        chatResponse({
          assistant_message: "Need more fields.",
          missing_fields: ["inlet", "chips.1.chip_type"],
          parameter_summary: {
            sample_name: "chat-forward",
            chip_count: 6,
            inlet1: null,
            inlet2: null,
            chips: [{ position: 1, chip_type: "5to4", left_width_mm: 0.1 }],
            missing_count: 2,
            missing_fields: ["inlet", "chips.1.chip_type"],
          },
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "use 6 chips for forward prediction");

    const summary = await screen.findByRole("region", { name: "Parameter Summary" });
    expect(within(summary).getByText("chat-forward")).toBeInTheDocument();
    expect(within(summary).getByText("6")).toBeInTheDocument();
    expect(within(summary).getByText("Missing Parameters")).toBeInTheDocument();
    expect(within(summary).getByText("inlet")).toBeInTheDocument();
    expect(within(summary).getAllByText("-").length).toBeGreaterThan(0);
  });

  it("renders confirmation and runs only through /chat/message", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "ready_for_confirmation",
          assistant_message: "Ready.",
          confirmation: {
            mode: "forward",
            summary: completeForwardSummary(),
          },
          parameter_summary: completeForwardSummary(),
        }),
      ),
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "Done.",
          forward_prediction: forwardPrediction(),
          parameter_summary: completeForwardSummary(),
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "show parameters");
    await screen.findByText("Confirm Forward Prediction Parameters");
    await user.click(screen.getByRole("button", { name: "Run Prediction" }));

    expect(await screen.findByText("Forward Prediction Result")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/chat/message");
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v1/chat/message");
    expect(String(fetchMock.mock.calls[1][0])).not.toContain("/api/v1/forward");
    expect(requestBody(fetchMock, 1).message).toBe("run");
  });

  it("blocks rapid Run Prediction clicks with the shared synchronous lock", async () => {
    const user = userEvent.setup();
    let resolveRun: (response: Response) => void = () => undefined;
    const pendingRun = new Promise<Response>((resolve) => {
      resolveRun = resolve;
    });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "ready_for_confirmation",
          assistant_message: "Ready.",
          confirmation: {
            mode: "forward",
            summary: completeForwardSummary(),
          },
          parameter_summary: completeForwardSummary(),
        }),
      ),
      pendingRun,
    );
    renderChatPage();

    await sendMessage(user, "show parameters");
    const run = await screen.findByRole("button", { name: "Run Prediction" });
    fireEvent.click(run);
    fireEvent.click(run);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestBody(fetchMock, 1).message).toBe("run");
    resolveRun(jsonResponse(chatResponse({ state: "completed", assistant_message: "Done." })));
    expect(await screen.findByText("Done.")).toBeInTheDocument();
  });

  it("focuses the composer when continuing from confirmation", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(
        chatResponse({
          state: "ready_for_confirmation",
          assistant_message: "Ready.",
          confirmation: { mode: "reverse", summary: reverseSummary() },
          parameter_summary: reverseSummary(),
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "show parameters");
    await user.click(await screen.findByRole("button", { name: "Continue Editing" }));

    expect(messageBox()).toHaveFocus();
  });

  it("renders forward_prediction rows from the backend response", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "Done.",
          forward_prediction: forwardPrediction(4),
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "run");

    expect(await screen.findByText("Forward Prediction Result")).toBeInTheDocument();
    expect(screen.getByText("0.123457")).toBeInTheDocument();
    expect(screen.getByText("3.123457")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/flow|seed|mean|std/i);
  });
});

describe("Assistant reverse task handling", () => {
  it("renders a running reverse task and polls until completed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      jsonResponse(completedReverseTask()),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    expect(await screen.findByText(/Task ID: task-1/)).toBeInTheDocument();
    expect(screen.getByText(/Status: Running/)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(await screen.findByText(/Status: Completed/)).toBeInTheDocument();
    expect(screen.getByText("MAE: 0.001000")).toBeInTheDocument();
    expect(screen.getAllByText("0.101000")).toHaveLength(6);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v1/reverse-tasks/task-1");
  });

  it("does not start overlapping reverse polling requests", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    let resolveFirstPoll: (response: Response) => void = () => undefined;
    const firstPoll = new Promise<Response>((resolve) => {
      resolveFirstPoll = resolve;
    });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      firstPoll,
      jsonResponse(runningReverseTask()),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveFirstPoll(jsonResponse(runningReverseTask()));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(2999);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("schedules the next reverse poll only after a running response resolves", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      jsonResponse(runningReverseTask()),
      jsonResponse(runningReverseTask()),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each(["cancelled", "failed"])("stops polling after reverse task %s", async (status) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      jsonResponse({ ...runningReverseTask(), status }),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
      await vi.advanceTimersByTimeAsync(6000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText(new RegExp(`Status: ${capitalize(status)}`))).toBeInTheDocument();
  });

  it("stops polling after reverse task completed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      jsonResponse(completedReverseTask()),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
      await vi.advanceTimersByTimeAsync(6000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/Status: Completed/)).toBeInTheDocument();
  });

  it("stops polling and shows a communication error when reverse polling fails", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const rejectedPoll = Promise.reject<Response>(new Error("offline"));
    rejectedPoll.catch(() => undefined);
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      rejectedPoll,
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("The reverse-prediction task failed.");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("cleans up pending reverse polling timers on unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
    );
    const { unmount } = renderChatPage();

    await sendMessage(user, "run reverse");
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ignores a stale reverse poll response after a new reverse task starts", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    let resolveTaskA: (response: Response) => void = () => undefined;
    const pendingTaskA = new Promise<Response>((resolve) => {
      resolveTaskA = resolve;
    });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task A created.",
          reverse_task: { task_id: "task-A", status: "running" },
        }),
      ),
      pendingTaskA,
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task B created.",
          reverse_task: { task_id: "task-B", status: "running" },
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "run reverse A");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await sendMessage(user, "run reverse B");
    expect(await screen.findByText(/Task ID: task-B/)).toBeInTheDocument();

    resolveTaskA(jsonResponse({ ...completedReverseTask(), task_id: "task-A" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText(/Task ID: task-B/)).toBeInTheDocument();
    expect(screen.queryByText(/Task ID: task-A/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("cancels a running reverse task through chat, not direct DELETE", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "The reverse prediction task has been cancelled.",
          reverse_task: { task_id: "task-1", status: "cancelled" },
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    await user.click(await screen.findByRole("button", { name: "Cancel Task" }));

    expect(await screen.findByText("The reverse prediction task has been cancelled.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);
    expect(requestBody(fetchMock, 1).message).toBe("cancel");
  });

  it("blocks rapid Cancel Task clicks with the shared synchronous lock", async () => {
    const user = userEvent.setup();
    let resolveCancel: (response: Response) => void = () => undefined;
    const pendingCancel = new Promise<Response>((resolve) => {
      resolveCancel = resolve;
    });
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      pendingCancel,
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    const cancel = await screen.findByRole("button", { name: "Cancel Task" });
    fireEvent.click(cancel);
    fireEvent.click(cancel);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestBody(fetchMock, 1).message).toBe("cancel");
    resolveCancel(
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "The reverse prediction task has been cancelled.",
          reverse_task: { task_id: "task-1", status: "cancelled" },
        }),
      ),
    );
    expect(await screen.findByText("The reverse prediction task has been cancelled.")).toBeInTheDocument();
  });

  it("clears an old completed reverse card when a new forward flow starts", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "Reverse completed.",
          reverse_task: { task_id: "task-1", status: "completed" },
        }),
      ),
      jsonResponse(
        chatResponse({
          state: "collecting",
          intent: "start_forward",
          assistant_message: "Forward started.",
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    expect(await screen.findByText(/Task ID: task-1/)).toBeInTheDocument();
    await sendMessage(user, "start forward");

    expect(await screen.findByText("Forward started.")).toBeInTheDocument();
    expect(screen.queryByText(/Task ID: task-1/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps a running reverse card during ordinary chat status refreshes", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "running",
          assistant_message: "Reverse task created.",
          reverse_task: { task_id: "task-1", status: "running" },
        }),
      ),
      jsonResponse(
        chatResponse({
          state: "collecting",
          intent: "show_parameters",
          assistant_message: "Parameters updated.",
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    expect(await screen.findByText(/Task ID: task-1/)).toBeInTheDocument();
    await sendMessage(user, "show parameters");

    expect(await screen.findByText("Parameters updated.")).toBeInTheDocument();
    expect(screen.getByText(/Task ID: task-1/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not show a forward result together with an old completed reverse card", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "Reverse completed.",
          reverse_task: { task_id: "task-1", status: "completed" },
        }),
      ),
      jsonResponse(
        chatResponse({
          state: "completed",
          assistant_message: "Forward completed.",
          forward_prediction: forwardPrediction(4),
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "run reverse");
    expect(await screen.findByText(/Task ID: task-1/)).toBeInTheDocument();
    await sendMessage(user, "run forward");

    expect(await screen.findByText("Forward Prediction Result")).toBeInTheDocument();
    expect(screen.queryByText(/Task ID: task-1/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("Assistant clarification and errors", () => {
  it("shows ambiguous input as clarification instead of runtime failure", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(
        chatResponse({
          assistant_message: "The message is ambiguous.",
          error: { code: "AMBIGUOUS_INPUT", message: "Ambiguous input." },
        }),
      ),
    );
    renderChatPage();

    await sendMessage(user, "0.2");

    expect(await screen.findByText("Clarification")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows API failures as error state", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(new Error("offline")));
    renderChatPage();

    await sendMessage(user, "use 6 chips");

    expect(await screen.findByRole("alert")).toHaveTextContent("The backend service is unavailable");
    expect(screen.getByText("The request failed. Please try again.")).toBeInTheDocument();
  });
});

function renderChatPage({ withLanguageSwitcher = false }: { withLanguageSwitcher?: boolean } = {}) {
  window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
  return renderWithI18n(
    <MemoryRouter>
      {withLanguageSwitcher ? <LanguageSwitcher /> : null}
      <ChatPage />
    </MemoryRouter>,
  );
}

async function sendMessage(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.clear(messageBox());
  await user.type(messageBox(), text);
  await user.click(screen.getByRole("button", { name: /Send|发送/ }));
}

function messageBox() {
  return screen.getByRole("textbox", { name: /Message|输入消息/ }) as HTMLTextAreaElement;
}

function chatResponse(overrides: Partial<ChatMessageResponse> = {}): ChatMessageResponse {
  return { ...baseChatResponse(), ...overrides };
}

function baseChatResponse(): ChatMessageResponse {
  return {
    session_id: "session-1",
    state: "collecting",
    intent: "set_chip_count",
    assistant_message: "Recorded.",
    missing_fields: [],
    parameter_summary: {},
    confirmation: null,
    forward_prediction: null,
    reverse_task: null,
    error: null,
  };
}

function completeForwardSummary() {
  return {
    sample_name: "chat-forward",
    chip_count: 6,
    inlet1: 1,
    inlet2: 0,
    chips: Array.from({ length: 6 }, (_, index) => ({
      position: index + 1,
      chip_type: "5to4",
      left_width_mm: 0.1,
      right_width_mm: 0.2,
      left_bend_straight_distance_mm: 10 + index,
      right_bend_straight_distance_mm: 20 + index,
    })),
  };
}

function reverseSummary() {
  return {
    inlet1: 0,
    inlet2: 1,
    target_concentrations: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
  };
}

function forwardPrediction(length = 6) {
  return {
    sample_name: "chat-forward",
    inlets: { inlet1: 1, inlet2: 0 },
    chip_count: length,
    predictions: Array.from({ length }, (_, index) => ({
      position: index + 1,
      point: `y${index + 1}`,
      chip_type: "5to4",
      concentration: index + 0.1234567,
    })),
  };
}

function runningReverseTask() {
  return {
    task_id: "task-1",
    status: "running",
    created_at: "2026-07-27T00:00:00Z",
    started_at: "2026-07-27T00:00:00Z",
    warnings: [],
  };
}

function completedReverseTask() {
  return {
    ...runningReverseTask(),
    status: "completed",
    finished_at: "2026-07-27T00:00:01Z",
    elapsed_seconds: 1,
    result: {
      inlet1: 0,
      inlet2: 1,
      target_concentrations: [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
      chips: Array.from({ length: 6 }, (_, index) => ({
        position: index + 1,
        point_labels: [`P${index * 2 + 1}`, `P${index * 2 + 2}`],
        chip_type: "5to4",
        left_width_mm: 0.261,
        right_width_mm: 0.138,
        left_bend_class: 5,
        right_bend_class: 4,
        left_distance_mm: 31,
        right_distance_mm: 25,
        target_concentration: 0.1,
        predicted_concentration: 0.101,
        absolute_error: 0.001,
      })),
      metrics: {
        mae: 0.001,
        rmse: 0.001,
        maxae: 0.001,
        spearman: 1,
        internal_screening_pass: true,
        selected_restart: 0,
      },
      warnings: [],
      notes: ["CFD verification is still required."],
    },
  };
}

function requestBody(fetchMock: ReturnType<typeof mockFetch>, index: number) {
  return JSON.parse(String(fetchMock.mock.calls[index][1]?.body));
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(...responses: Array<Response | Promise<Response>>) {
  const fetchMock = vi.fn<typeof fetch>();
  for (const response of responses) {
    fetchMock.mockImplementationOnce(() =>
      response instanceof Response ? Promise.resolve(response) : response,
    );
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function capitalize(value: string) {
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}
