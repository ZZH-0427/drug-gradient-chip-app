import { act } from "react";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY } from "../i18n/locale";
import { LanguageSwitcher } from "../i18n/LanguageSwitcher";
import { renderWithI18n } from "../test/renderWithI18n";
import { REVERSE_TASK_STORAGE_KEY, ReversePage } from "./ReversePage";

const LEGACY_TARGET_RANGE_WARNING =
  "Target concentrations include values outside the recommended dense training range [0.10, 0.95]; review the result carefully.";

beforeEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("Reverse localized form", () => {
  it("renders Chinese reverse prediction copy and never shows the old product name", () => {
    renderReversePage();

    expect(screen.getByRole("heading", { name: "反向预测" })).toBeInTheDocument();
    expect(screen.getByText("芯片结构优化")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始反向预测" })).toBeInTheDocument();
    expect(document.title).toBe("反向预测 | 药物浓度梯度芯片");
    expect(document.body.textContent).not.toContain("反向设计");
    expect(document.body.textContent).not.toContain("Reverse Design");
  });

  it("switches to English without clearing target concentrations or inlet selection", async () => {
    const user = userEvent.setup();
    renderReversePage();

    await user.click(screen.getByRole("radio", { name: "Inlet1" }));
    await user.clear(screen.getByRole("spinbutton", { name: "y1 目标浓度" }));
    await user.type(screen.getByRole("spinbutton", { name: "y1 目标浓度" }), "0.42");
    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(screen.getByRole("heading", { name: "Reverse Prediction" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Reverse Prediction" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Inlet1" })).toBeChecked();
    expect(screen.getByRole("spinbutton", { name: "y1 Target Concentration" })).toHaveValue(0.42);
    expect(document.title).toBe("Reverse Prediction | Drug Concentration Gradient Chip");
  });

  it("uses a segmented inlet selector and submits Inlet1 as inlet1=1 and inlet2=0", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    renderReversePage();

    expect(screen.queryByText("入口1浓度")).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: "Inlet1" }));
    await user.click(screen.getByRole("button", { name: "开始反向预测" }));

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    expectPostedPayload(fetchMock, { inlet1: 1, inlet2: 0 });
  });

  it.each(["zh-CN", "en"])("submits default Inlet2 as inlet1=0 and inlet2=1 in %s", async (locale) => {
    const user = userEvent.setup();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    renderReversePage();

    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();
    await user.click(startReverseButton());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expectPostedPayload(fetchMock, { inlet1: 0, inlet2: 1 });
  });

  it("keeps Inlet2 selected across language switching before submitting the same payload", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    renderReversePage();

    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "EN" }));
    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Start Reverse Prediction" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expectPostedPayload(fetchMock, { inlet1: 0, inlet2: 1 });
  });

  it("restores the official example and resets to Inlet2", async () => {
    const user = userEvent.setup();
    renderReversePage();

    await user.click(screen.getByRole("radio", { name: "Inlet1" }));
    await user.clear(screen.getByRole("spinbutton", { name: "y1 目标浓度" }));
    await user.type(screen.getByRole("spinbutton", { name: "y1 目标浓度" }), "0.42");
    await user.click(screen.getByRole("button", { name: "恢复官方示例" }));

    expect(screen.getByRole("radio", { name: "Inlet2" })).toBeChecked();
    expect(screen.getByRole("spinbutton", { name: "y1 目标浓度" })).toHaveValue(0.08);
  });

  it("renders exactly six compact target inputs with accessible labels", () => {
    const { container } = renderReversePage();

    for (let index = 1; index <= 6; index += 1) {
      expect(screen.getByRole("spinbutton", { name: `y${index} 目标浓度` })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("spinbutton")).toHaveLength(6);
    expect(container.querySelectorAll(".reverse-target-input")).toHaveLength(6);
    expect(container.querySelector(".reverse-target-table")).toBeInTheDocument();
  });

  it.each([
    ["zh-CN", /\[0\.10, 0\.95\]/],
    ["en", /Some target concentrations fall outside the recommended dense training range \[0\.10, 0\.95\]/],
  ])("allows the official 0.08 target value to submit without showing the %s pre-submit warning", async (locale, warning) => {
    const user = userEvent.setup();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    renderReversePage();

    expect(screen.getByRole("spinbutton", { name: /y1/ })).toHaveValue(0.08);
    expect(screen.queryByText(warning)).not.toBeInTheDocument();
    expect(startReverseButton()).toBeEnabled();
    await user.click(startReverseButton());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expectPostedPayload(fetchMock, { inlet1: 0, inlet2: 1 });
  });
});

describe("Reverse localized task submission and cancellation", () => {
  it("stores task_id after creating a task and does not store request or result payloads", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    renderReversePage();

    await user.click(screen.getByRole("button", { name: "开始反向预测" }));

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-1");
    expect(window.sessionStorage).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/reverse-tasks");
  });

  it("prevents duplicate create requests while create is pending", async () => {
    const user = userEvent.setup();
    const createPromise = new Promise<Response>(() => undefined);
    const fetchMock = mockFetch(createPromise);
    renderReversePage();

    const submit = screen.getByRole("button", { name: "开始反向预测" });
    await user.click(submit);
    await user.click(submit);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not post a new task when a local task is already running", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse({ task_id: "task-1", status: "running" }, 202));
    renderReversePage();

    await user.click(screen.getByRole("button", { name: "开始反向预测" }));
    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始反向预测" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-1");
  });

  it("shows localized busy message without starting polling", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    const fetchMock = mockFetch(
      jsonResponse({ error: { code: "REVERSE_TASK_BUSY", message: "server detail" } }, 409),
    );
    renderReversePage();

    await user.click(screen.getByRole("button", { name: "Start Reverse Prediction" }));

    expect(await screen.findByText("A reverse-prediction task is already running. Please wait for it to finish.")).toBeInTheDocument();
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
    renderReversePage();

    await user.click(screen.getByRole("button", { name: "开始反向预测" }));
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
    renderReversePage();

    await user.click(screen.getByRole("button", { name: "开始反向预测" }));
    await user.click(await screen.findByRole("button", { name: "取消任务" }));

    expect(await screen.findByText("该反向预测任务当前不可取消。")).toBeInTheDocument();
    expect(screen.getByText("正在运行")).toBeInTheDocument();
  });
});

describe("Reverse localized results", () => {
  it("shows unknown completed result notes verbatim without mapping them to failed", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask(["A reviewer-specific completed-result note."])));

    renderReversePage();

    expect(await screen.findByText("Completed, Elapsed 1.00 seconds")).toBeInTheDocument();
    expect(screen.getByText("A reviewer-specific completed-result note.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("The reverse-prediction task failed.");
  });

  it("localizes known completed result notes", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    renderReversePage();

    expect(await screen.findByText("Completed, Elapsed 1.00 seconds")).toBeInTheDocument();
    expect(
      screen.getByText("Internal screening only indicates that the structure was evaluated by the same Physics-GNN surrogate model."),
    ).toBeInTheDocument();
    expect(screen.getByText("The final design must still be independently verified using Fluent/CFD.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("The reverse-prediction task failed.");
  });

  it("still shows a real reverse failure when task status is failed", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(failedTask("REVERSE_TASK_FAILED", "server detail")));

    renderReversePage();

    expect(await screen.findByText("The reverse-prediction task failed.")).toBeInTheDocument();
    expect(screen.getByText("Failed, Elapsed 1.00 seconds")).toBeInTheDocument();
  });

  it("hides result warnings while preserving Chinese notes, metrics, and result rows", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    renderReversePage();

    expect(await screen.findByText("已完成, 耗时 1.00 秒")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("[0.10, 0.95]");
    expect(screen.getByText("MAE: 0.001000")).toBeInTheDocument();
    expect(screen.getByText("RMSE: 0.001000")).toBeInTheDocument();
    expect(screen.getByText("MaxAE: 0.001000")).toBeInTheDocument();
    expect(screen.getByText("Spearman: 1.000000")).toBeInTheDocument();
    expect(screen.getAllByText("0.101000")).toHaveLength(6);
    expect(screen.getByText("内部筛选仅表示该结构已通过同一 Physics-GNN 代理模型的检查。")).toBeInTheDocument();
    expect(screen.getByText("最终设计仍需使用 Fluent/CFD 进行独立验证。")).toBeInTheDocument();
    expect(screen.getByText("反向预测中的复算浓度由反向优化所使用的内部代理模型生成，可能与独立正向预测结果存在轻微差异。")).toBeInTheDocument();
    expect(screen.getByText("反向预测采用数值优化，不同计算设备可能得到不同但均满足代理模型筛选条件的方案。")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(LEGACY_TARGET_RANGE_WARNING);
    expect(document.body.textContent).not.toContain("反向设计");
    expect(document.body.textContent).not.toContain("Reverse Design");
  });

  it.each([
    ["queued", "等待运行", "Queued"],
    ["running", "正在运行", "Running"],
    ["preparing_model", "正在准备模型", "Preparing Model"],
    ["optimizing", "正在优化结构", "Optimizing Structure"],
    ["refining", "正在细化结构", "Refining Structure"],
    ["verifying", "正在复算验证", "Verifying Prediction"],
    ["completed", "已完成", "Completed"],
    ["failed", "运行失败", "Failed"],
    ["cancelled", "已取消", "Cancelled"],
  ])("maps %s status to both locales", async (status, zhLabel, enLabel) => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse({ ...runningTask(), status }));
    const user = userEvent.setup();

    renderReversePage();

    expect(await screen.findByText(zhLabel)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "EN" }));
    expect(screen.getByText(enLabel)).toBeInTheDocument();
  });

  it("uses localized result table headers and hides flow and paths", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));

    renderReversePage();

    const resultSection = (await screen.findByRole("heading", { name: "Task Status" })).closest("section");
    expect(resultSection).not.toBeNull();
    expect(within(resultSection as HTMLElement).getByText("Chip Type")).toBeInTheDocument();
    expect(within(resultSection as HTMLElement).getByText("Surrogate-Predicted Concentration")).toBeInTheDocument();
    expect((resultSection as HTMLElement).textContent).toContain("Internal Screening: Passed");
    expect(document.body.textContent).not.toMatch(/flow|checkpoint|pytorch_geometric-master/i);
  });

  it("keeps completed results when switching language", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(completedTask()));
    const user = userEvent.setup();

    renderReversePage();

    expect(await screen.findAllByText("0.101000")).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(screen.getByText("Task Status")).toBeInTheDocument();
    expect(screen.getAllByText("0.101000")).toHaveLength(6);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();
  });

  it("does not offer cancellation after completion and allows starting a new task", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    const fetchMock = mockFetch(
      jsonResponse(completedTask()),
      jsonResponse({ task_id: "task-2", status: "running" }, 202),
    );
    const user = userEvent.setup();

    renderReversePage();

    expect(await screen.findByText("Completed, Elapsed 1.00 seconds")).toBeInTheDocument();
    expect(cancelTaskButton()).not.toBeInTheDocument();
    await user.click(screen.getByRole("heading", { name: "Task Status" }));
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "中文" }));
    expect(cancelTaskButton()).not.toBeInTheDocument();
    await user.click(startReverseButton());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "DELETE")).toBe(false);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v1/reverse-tasks");
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-2");
  });
});

describe("Reverse task refresh recovery", () => {
  it("restores a running task from sessionStorage and resumes polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    mockFetch(jsonResponse(runningTask()), jsonResponse(completedTask()));
    renderReversePage();

    expect(await screen.findByText("正在运行")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(await screen.findByText("已完成, 耗时 1.00 秒")).toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();
  });

  it.each([
    ["failed", failedTask("REVERSE_TASK_FAILED", "server detail")],
    ["cancelled", cancelledTask()],
  ])("restores terminal %s status, stops polling, and clears saved task_id", async (_, task) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = mockFetch(jsonResponse(task));
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");

    renderReversePage();

    await waitFor(() => expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears an invalid saved task_id after 404 and returns to submit state", async () => {
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "missing");
    mockFetch(jsonResponse({ error: { code: "REVERSE_TASK_NOT_FOUND" } }, 404));

    renderReversePage();

    await waitFor(() => expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull());
    expect(screen.getByRole("button", { name: "开始反向预测" })).toBeEnabled();
    expect(screen.queryByText("正在运行")).not.toBeInTheDocument();
  });

  it("clears polling on unmount without cancelling the backend task", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.sessionStorage.setItem(REVERSE_TASK_STORAGE_KEY, "task-1");
    const fetchMock = mockFetch(jsonResponse(runningTask()), jsonResponse(runningTask()));
    const view = renderReversePage();

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
      jsonResponse(failedTask("REVERSE_TASK_TIMEOUT", "server timeout")),
      jsonResponse({ task_id: "task-2", status: "running" }, 202),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderReversePage();

    await user.click(screen.getByRole("button", { name: "开始反向预测" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(await screen.findByText("反向预测任务超时。")).toBeInTheDocument();
    expect(screen.queryByText("正在运行")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBeNull();

    await user.click(screen.getByRole("button", { name: "开始反向预测" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(window.sessionStorage.getItem(REVERSE_TASK_STORAGE_KEY)).toBe("task-2");
  });
});

function renderReversePage() {
  return renderWithI18n(
    <>
      <LanguageSwitcher />
      <ReversePage />
    </>,
  );
}

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

function startReverseButton() {
  return screen.getByRole("button", { name: /Start Reverse Prediction|开始反向预测/ });
}

function cancelTaskButton() {
  return screen.queryByRole("button", { name: /Cancel Task|取消任务/ });
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

function completedTask(
  notes = [
    "Internal screening only means the structure was checked by the same Physics-GNN surrogate model.",
    "Final designs should still be independently verified with Fluent/CFD.",
  ],
) {
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
      notes,
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
