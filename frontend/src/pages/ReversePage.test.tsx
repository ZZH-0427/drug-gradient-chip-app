import { act } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REVERSE_TASK_STORAGE_KEY, ReversePage } from "./ReversePage";

const TARGET_RANGE_WARNING =
  "目标浓度中包含超出推荐密集训练范围 [0.10, 0.95] 的数值，请谨慎评估结果。";
const LEGACY_TARGET_RANGE_WARNING =
  "Target concentrations include values outside the recommended dense training range [0.10, 0.95]; review the result carefully.";
const INTERNAL_SCREENING_NOTE =
  "内部筛选仅表示该结构已通过同一 Physics-GNN 代理模型的检查。";
const CFD_NOTE = "最终设计仍需使用 Fluent/CFD 进行独立验证。";

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

describe("Reverse form", () => {
  it("uses a segmented inlet selector instead of numeric inlet inputs", async () => {
    const user = userEvent.setup();
    render(<ReversePage />);

    expect(screen.queryByText("入口1浓度")).not.toBeInTheDocument();
    expect(screen.queryByText("入口2浓度")).not.toBeInTheDocument();

    const inlet1 = screen.getByRole("radio", { name: "Inlet1" });
    const inlet2 = screen.getByRole("radio", { name: "Inlet2" });
    expect(inlet1).not.toBeChecked();
    expect(inlet2).toBeChecked();

    await user.click(inlet1);
    expect(inlet1).toBeChecked();
    expect(inlet2).not.toBeChecked();
  });

  it("sends Inlet1 as inlet1=1 and inlet2=0", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    render(<ReversePage />);

    await user.click(screen.getByRole("radio", { name: "Inlet1" }));
    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    expectPostedPayload(fetchMock, { inlet1: 1, inlet2: 0 });
  });

  it("sends Inlet2 as inlet1=0 and inlet2=1", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    expectPostedPayload(fetchMock, { inlet1: 0, inlet2: 1 });
  });

  it("restores the official example and resets to Inlet2", async () => {
    const user = userEvent.setup();
    render(<ReversePage />);

    await user.click(screen.getByRole("radio", { name: "Inlet1" }));
    await user.clear(screen.getByRole("spinbutton", { name: "y1 目标浓度" }));
    await user.type(screen.getByRole("spinbutton", { name: "y1 目标浓度" }), "0.42");
    await user.click(screen.getByRole("button", { name: "恢复官方示例" }));

    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();
    expect(screen.getByRole("spinbutton", { name: "y1 目标浓度" })).toHaveValue(0.08);
  });

  it("renders exactly six compact target inputs with accessible labels", () => {
    const { container } = render(<ReversePage />);

    for (let index = 1; index <= 6; index += 1) {
      expect(screen.getByRole("spinbutton", { name: `y${index} 目标浓度` })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6);
    expect(container.querySelectorAll(".reverse-target-input")).toHaveLength(6);
    expect(container.querySelector(".reverse-target-table")).toBeInTheDocument();
    expect(screen.queryByText("y1目标浓度")).not.toBeInTheDocument();
  });

  it("allows the official 0.08 target value to submit", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    render(<ReversePage />);

    expect(screen.getByRole("spinbutton", { name: "y1 目标浓度" })).toHaveValue(0.08);
    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("Reverse task submission and cancellation", () => {
  it("stores task_id after creating a task and does not store request or result payloads", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
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
    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交反向设计任务" })).toBeDisabled();
  });

  it("shows busy message without starting polling", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(
      jsonResponse({ error: { code: "REVERSE_TASK_BUSY", message: "server detail" } }, 409),
    );
    render(<ReversePage />);

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));

    expect(await screen.findByText("已有反向设计任务正在运行，请等待完成或取消后再提交。")).toBeInTheDocument();
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

    expect(await screen.findByText("该反向设计任务当前不可取消。")).toBeInTheDocument();
    expect(screen.getByText("正在运行")).toBeInTheDocument();
  });

  it("does not show cancel action after a completed task", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    render(<ReversePage />);

    expect(await screen.findByText("已完成，耗时 1.00 秒")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "取消任务" })).not.toBeInTheDocument();
  });
});

describe("Reverse results localization", () => {
  it("renders Chinese warning and notes without legacy English sentences", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    render(<ReversePage />);

    expect(await screen.findByText("已完成，耗时 1.00 秒")).toBeInTheDocument();
    expect(screen.getByText(TARGET_RANGE_WARNING)).toBeInTheDocument();
    expect(screen.getByText(INTERNAL_SCREENING_NOTE)).toBeInTheDocument();
    expect(screen.getByText(CFD_NOTE)).toBeInTheDocument();
    expect(
      screen.getByText(
        "反向设计中的复算浓度由反向优化所使用的内部代理模型生成，可能与独立正向预测结果存在轻微差异。",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "反向设计采用数值优化，不同计算设备可能得到不同但均满足代理模型筛选条件的设计方案。",
      ),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(LEGACY_TARGET_RANGE_WARNING);
    expect(document.body.textContent).not.toContain("Internal screening only");
    expect(document.body.textContent).not.toContain("Final designs should");
  });

  it.each([
    ["queued", "等待运行"],
    ["running", "正在运行"],
    ["preparing_model", "正在准备模型"],
    ["optimizing", "正在优化结构"],
    ["refining", "正在细化结构"],
    ["verifying", "正在复算验证"],
    ["completed", "已完成"],
    ["failed", "运行失败"],
    ["cancelled", "已取消"],
  ])("maps %s status to Chinese", async (status, label) => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse({ ...runningTask(), status }));

    render(<ReversePage />);

    expect(await screen.findByText(label)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(status);
  });

  it("uses Chinese result table headers", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    render(<ReversePage />);

    const table = await screen.findByRole("table", { name: "" });
    const resultSection = screen.getByRole("heading", { name: "任务状态" }).closest("section");
    expect(resultSection).not.toBeNull();
    expect(within(resultSection as HTMLElement).getByText("芯片类型")).toBeInTheDocument();
    expect(within(resultSection as HTMLElement).getByText("复算浓度")).toBeInTheDocument();
    expect(table).toBeInTheDocument();
  });
});

describe("Reverse task refresh recovery", () => {
  it("restores a running task from sessionStorage and resumes polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(runningTask()), jsonResponse(completedTask()));
    render(<ReversePage />);

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
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
    expect(screen.queryByText("正在运行")).not.toBeInTheDocument();
  });

  it("clears polling on unmount without cancelling the backend task", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    const fetchMock = mockFetch(jsonResponse(runningTask()), jsonResponse(runningTask()));
    const view = render(<ReversePage />);

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
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
    expect(screen.queryByText("正在运行")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-2");
  });
});

function expectPostedPayload(
  fetchMock: ReturnType<typeof mockFetch>,
  expected: { inlet1: number; inlet2: number },
) {
  const request = fetchMock.mock.calls[0][1];
  expect(request?.body).toBeTypeOf("string");
  const payload = JSON.parse(request?.body as string);
  expect(payload.inlet1).toBe(expected.inlet1);
  expect(payload.inlet2).toBe(expected.inlet2);
}

function runningTask(status = "running") {
  return {
    task_id: "task-1",
    status,
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
    warnings: [LEGACY_TARGET_RANGE_WARNING],
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
      notes: [
        "Internal screening only means the structure was checked by the same Physics-GNN surrogate model.",
        "Final designs should still be independently verified with Fluent/CFD.",
      ],
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
