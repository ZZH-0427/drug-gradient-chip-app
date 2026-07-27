import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const statusReady = {
  ready: true,
  model_name: "physics-gnn",
  supported_chip_counts: [6],
  public_output: "concentration",
  device: "cpu",
  forward: {
    ready: true,
    supported_chip_counts: [6],
    output: "concentration",
  },
  reverse: {
    ready: true,
    supported_chip_counts: [6],
    execution_mode: "async",
    max_concurrent_tasks: 1,
  },
};

function successPayload(length = 6) {
  return {
    sample_name: "DP 0",
    inlets: { inlet1: 1, inlet2: 0 },
    chip_count: 6,
    predictions: Array.from({ length }, (_, index) => ({
      position: index + 1,
      point: `y${index + 1}`,
      chip_type: ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1"][index] ?? "1to1",
      concentration: index + 0.1234567,
    })),
  };
}

function reverseCompletedPayload() {
  return {
    task_id: "task-1",
    status: "completed",
    created_at: "2026-07-27T00:00:00Z",
    started_at: "2026-07-27T00:00:00Z",
    finished_at: "2026-07-27T00:00:01Z",
    elapsed_seconds: 1,
    warnings: ["目标浓度包含推荐训练密集范围 [0.10, 0.95] 之外的值，任务仍会运行，但结果需要额外复核。"],
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

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("App navigation", () => {
  it("renders forward and reverse entries on the home page", () => {
    renderApp("/");

    expect(screen.getByRole("link", { name: "正向预测" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "反向设计" })).toBeInTheDocument();
  });

  it("renders the reverse page", () => {
    renderApp("/reverse");

    expect(screen.getByRole("heading", { name: "反向设计" })).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(8);
  });

  it("shows not found for unknown routes", () => {
    renderApp("/missing");

    expect(screen.getByRole("heading", { name: /页面|椤/ })).toBeInTheDocument();
  });
});

describe("Forward workflow", () => {
  it("renders default six-chip form and chip count options 4 through 8", async () => {
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await waitFor(() => expect(screen.getByRole("combobox", { name: "芯片数量" })).toHaveValue("6"));
    expect(positionCells()).toHaveLength(6);
    expect(screen.getByText("P1/P2")).toBeInTheDocument();
    expect(screen.getByText("P11/P12")).toBeInTheDocument();

    const options = within(screen.getByRole("combobox", { name: "芯片数量" })).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["4", "5", "6", "7", "8"]);
  });

  it("selecting 4 renders four positions and blocks prediction", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await user.selectOptions(await screen.findByRole("combobox", { name: "芯片数量" }), "4");

    expect(positionCells()).toHaveLength(4);
    expect(screen.getByText("P7/P8")).toBeInTheDocument();
    expect(screen.queryByText("P9/P10")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("submits chip_count=6 and displays concentration-only results", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderApp("/forward");

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: /确认|纭/ }));
    await user.click(screen.getByRole("button", { name: /运行|杩/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("0.123457")).toBeInTheDocument();
    expect(screen.queryByText("flow")).not.toBeInTheDocument();
    expect(screen.queryByText("seed_values")).not.toBeInTheDocument();

    const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(request.chip_count).toBe(6);
    expect(request.chips).toHaveLength(6);
  });
});

describe("Reverse workflow", () => {
  it("restores the official six-target example", async () => {
    const user = userEvent.setup();
    renderApp("/reverse");

    await user.clear(screen.getByRole("spinbutton", { name: "y1目标浓度" }));
    await user.type(screen.getByRole("spinbutton", { name: "y1目标浓度" }), "0.33");
    await user.click(screen.getByRole("button", { name: "恢复官方示例" }));

    expect(screen.getByRole("spinbutton", { name: "入口1浓度" })).toHaveValue(0);
    expect(screen.getByRole("spinbutton", { name: "入口2浓度" })).toHaveValue(1);
    expect(screen.getByRole("spinbutton", { name: "y1目标浓度" })).toHaveValue(0.08);
    expect(screen.getByRole("spinbutton", { name: "y6目标浓度" })).toHaveValue(0.58);
  });

  it("creates a reverse task and polls completed results", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const fetchMock = mockFetch(
      jsonResponse({ task_id: "task-1", status: "running" }, 202),
      jsonResponse(reverseCompletedPayload()),
    );
    renderApp("/reverse");

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    expect(await screen.findByText("运行中")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(await screen.findByText("已完成，耗时 1.00 秒")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "复算浓度" })).toBeInTheDocument();
    expect(screen.getByText("内部筛选: 通过")).toBeInTheDocument();
    expect(screen.queryByText("flow")).not.toBeInTheDocument();

    const request = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(request.target_concentrations).toHaveLength(6);
    expect(fetchMock.mock.calls[1][0]).toContain("/api/v1/reverse-tasks/task-1");
  });

  it("shows a dedicated busy message", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(
        {
          error: {
            code: "REVERSE_TASK_BUSY",
            message: "已有反向设计任务正在运行，请等待完成或取消后再提交。",
          },
        },
        409,
      ),
    );
    renderApp("/reverse");

    await user.click(screen.getByRole("button", { name: "提交反向设计任务" }));
    expect(await screen.findByText("已有反向设计任务正在运行，请等待完成或取消后再提交。")).toBeInTheDocument();
  });
});

function renderApp(initialPath: string) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
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

function positionCells() {
  return screen.getAllByText((_, element) => element?.textContent?.match(/^位置 \d+$/) !== null);
}
