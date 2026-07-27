import { act } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REVERSE_TASK_STORAGE_KEY, ReversePage } from "./ReversePage";

beforeEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Reverse task submission and cancellation", () => {
  it("stores task_id after creating a task and does not store request or result payloads", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(await screen.findByText("运行中")).toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-1");
    expect(window.sessionStorage).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/reverse-tasks");
  });

  it("prevents duplicate create requests while create is pending", async () => {
    const user = userEvent.setup();
    const createPromise = new Promise<Response>(() => undefined);
    const fetchMock = mockFetch(createPromise);
    render(<ReversePage />);

    const submit = screen.getByRole("button", { name: "提交反向设计任务" });
    await user.click(submit);
    await user.click(submit);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not post a new task when a local task is already running", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    expect(await screen.findByText("运行中")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交反向设计任务" })).toBeDisabled();
  });

  it("shows busy message without starting polling", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse({ error: { code: "REVERSE_TASK_BUSY", message: "server detail" } }, 409),
    );
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(await screen.findByText(/已有反向设计任务|宸叉湁/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();
  });

  it("calls DELETE once when cancelling a running task and clears task_id after success", async () => {
    const user = userEvent.setup();
    let resolveCancel: (response: Response) => void = () => undefined;
    const cancelPromise = new Promise<Response>((resolve) => {
      resolveCancel = resolve;
    });
    const fetchMock = mockFetch(
      jsonResponse({ task_id: "task-1", status: "running" }, 202),
      cancelPromise,
    );
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    const cancel = await screen.findByRole("button", { name: "取消任务" });
    await user.click(cancel);
    await user.click(cancel);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v1/reverse-tasks/task-1");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("DELETE");

    resolveCancel(jsonResponse(cancelledTask()));
    await waitFor(() => expect(document.body.textContent).toContain("已取消"));
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();
  });

  it("does not fake cancelled state when cancel fails", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse({ task_id: "task-1", status: "running" }, 202),
      jsonResponse({ error: { code: "REVERSE_TASK_NOT_CANCELLABLE" } }, 409),
    );
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    await user.click(await screen.findByRole("button", { name: "取消任务" }));

    expect(await screen.findByText(/不可取消|涓嶅彲/)).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("does not show cancel action after a completed task", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    render(<ReversePage />);

    expect(await screen.findByText("已完成，耗时 1.00 秒")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "取消任务" })).not.toBeInTheDocument();
  });
});

describe("Reverse task refresh recovery", () => {
  it("restores a running task from sessionStorage and resumes polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(runningTask()), jsonResponse(completedTask()));
    render(<ReversePage />);

    expect(await screen.findByText("运行中")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(await screen.findByText("已完成，耗时 1.00 秒")).toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();
  });

  it("restores completed task results and clears saved task_id", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    render(<ReversePage />);

    expect(await screen.findByText("已完成，耗时 1.00 秒")).toBeInTheDocument();
    expect(screen.getAllByText("0.101000")).toHaveLength(6);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();
  });

  it.each([
    ["failed", failedTask("REVERSE_TASK_FAILED", "反向设计任务失败。")],
    ["cancelled", cancelledTask()],
  ])("restores terminal %s status, stops polling, and clears saved task_id", async (_, task) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = mockFetch(jsonResponse(task));
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");

    render(<ReversePage />);

    await waitFor(() => expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears an invalid saved task_id after 404 and returns to submit state", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "missing");
    mockFetch(jsonResponse({ error: { code: "REVERSE_TASK_NOT_FOUND" } }, 404));

    render(<ReversePage />);

    await waitFor(() => expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull());
    expect(screen.getByRole("button", { name: "提交反向设计任务" })).toBeEnabled();
    expect(screen.queryByText("运行中")).not.toBeInTheDocument();
  });

  it("clears polling on unmount without cancelling the backend task", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    const fetchMock = mockFetch(jsonResponse(runningTask()), jsonResponse(runningTask()));
    const view = render(<ReversePage />);

    expect(await screen.findByText("运行中")).toBeInTheDocument();
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-1");
  });

  it("handles reverse timeout as terminal failure and allows a new task", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = mockFetch(
      jsonResponse({ task_id: "task-1", status: "running" }, 202),
      jsonResponse(failedTask("REVERSE_TASK_TIMEOUT", "反向设计任务超时。")),
      jsonResponse({ task_id: "task-2", status: "running" }, 202),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(await screen.findByText("反向设计任务超时。")).toBeInTheDocument();
    expect(screen.queryByText("运行中")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-2");
  });
});

function runningTask() {
  return {
    task_id: "task-1",
    status: "running",
    created_at: "2026-07-27T00:00:00Z",
    started_at: "2026-07-27T00:00:00Z",
    warnings: [],
  };
}

function cancelledTask() {
  return {
    task_id: "task-1",
    status: "cancelled",
    created_at: "2026-07-27T00:00:00Z",
    started_at: "2026-07-27T00:00:00Z",
    finished_at: "2026-07-27T00:00:01Z",
    elapsed_seconds: 1,
    warnings: [],
  };
}

function failedTask(code: string, message: string) {
  return {
    task_id: "task-1",
    status: "failed",
    created_at: "2026-07-27T00:00:00Z",
    started_at: "2026-07-27T00:00:00Z",
    finished_at: "2026-07-27T00:00:01Z",
    elapsed_seconds: 1,
    error: { code, message },
    warnings: [],
  };
}

function completedTask() {
  return {
    task_id: "task-1",
    status: "completed",
    created_at: "2026-07-27T00:00:00Z",
    started_at: "2026-07-27T00:00:00Z",
    finished_at: "2026-07-27T00:00:01Z",
    elapsed_seconds: 1,
    warnings: [],
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
      notes: ["最终设计仍应使用 Fluent/CFD 独立验证。"],
    },
  };
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
