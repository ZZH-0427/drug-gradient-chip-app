import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const statusReady = {
  ready: true,
  model_name: "forward-ensemble",
  ensemble_size: 5,
  seeds: [42, 52, 62, 72, 82],
  device: "cpu",
};

const successPayload = {
  sample_name: "DP 0",
  inlets: { inlet1: 1, inlet2: 0 },
  ensemble_seeds: [42, 52, 62, 72, 82],
  predictions: Array.from({ length: 6 }, (_, index) => ({
    position: index + 1,
    point: `y${index + 1}`,
    chip_type: ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1"][index],
    mean: index + 0.1234567,
    std: 0.01 * (index + 1),
    seed_values: {
      "42": index + 1,
      "52": index + 2,
      "62": index + 3,
      "72": index + 4,
      "82": index + 5,
    },
  })),
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App navigation", () => {
  it("renders home entries and navigates to reverse placeholder", async () => {
    const user = userEvent.setup();
    renderApp("/");

    expect(screen.getByRole("heading", { name: "药物浓度梯度芯片预测系统" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "正向预测" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "反向预测" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "反向预测" }));

    expect(screen.getByRole("heading", { name: "反向预测尚未接入" })).toBeInTheDocument();
    expect(screen.getByText("当前系统只集成了正向预测模型，反向模型逻辑和运行时接口尚不可用。")).toBeInTheDocument();
  });
});

describe("Forward workflow", () => {
  it("renders six fixed positions, generated chip options, and mutually exclusive inlet choices", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    expect(screen.getAllByText(/^位置 \d$/)).toHaveLength(6);

    const firstSelect = screen.getByLabelText("位置 1 芯片类型");
    expect(within(firstSelect).getAllByRole("option")).toHaveLength(36);
    expect(within(firstSelect).getByRole("option", { name: "6to6" })).toBeInTheDocument();

    const inlet1 = screen.getByRole("radio", { name: "inlet1=1, inlet2=0" });
    const inlet2 = screen.getByRole("radio", { name: "inlet1=0, inlet2=1" });
    expect(inlet1).toBeChecked();
    await user.click(inlet2);
    expect(inlet1).not.toBeChecked();
    expect(inlet2).toBeChecked();
  });

  it("blocks invalid frontend input without calling forward API", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.clear(screen.getByLabelText("样本名称"));
    await user.click(screen.getByRole("button", { name: "确认参数" }));

    expect(await screen.findByText("样本名称不能为空。")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("opens confirmation without calling API, then submits once and shows results", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.click(screen.getByRole("button", { name: "确认参数" }));

    expect(screen.getByRole("dialog", { name: "确认正向预测参数" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "运行预测" }));

    expect(await screen.findByRole("heading", { name: "预测结果" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Seed 42" })).toBeInTheDocument();
    expect(screen.getByText("0.123457")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("prevents duplicate prediction submits while loading", async () => {
    const user = userEvent.setup();
    let resolveForward: (response: Response) => void = () => undefined;
    const forwardPromise = new Promise<Response>((resolve) => {
      resolveForward = resolve;
    });
    const fetchMock = mockFetch(jsonResponse(statusReady), forwardPromise);
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.click(screen.getByRole("button", { name: "确认参数" }));
    const runButton = screen.getByRole("button", { name: "运行预测" });
    await user.click(runButton);
    await user.click(runButton);

    expect(screen.getByText("正向模型处理中")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    resolveForward(jsonResponse(successPayload));
    expect(await screen.findByRole("heading", { name: "预测结果" })).toBeInTheDocument();
  });

  it("handles unavailable model status and backend offline status", async () => {
    mockFetch(jsonResponse({ error: { code: "MODEL_NOT_READY", message: "not ready" } }, 503));
    renderApp("/forward");
    expect(await screen.findByText("正向模型暂不可用，请检查模型资产和后端状态。")).toBeInTheDocument();

    vi.unstubAllGlobals();
    mockRejectedFetch();
    renderApp("/forward");
    expect(await screen.findByText("后端服务不可用，请确认 FastAPI 已启动。")).toBeInTheDocument();
  });

  it.each([
    [422, "参数验证失败，请检查芯片参数。"],
    [500, "正向预测执行失败，请稍后重试。"],
    [503, "正向模型暂不可用，请检查模型资产和后端状态。"],
  ])("shows safe message for HTTP %s", async (status, message) => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(statusReady),
      jsonResponse({ error: { code: "BACKEND_DETAIL", message: "C:\\private\\trace" } }, status),
    );
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.click(screen.getByRole("button", { name: "确认参数" }));
    await user.click(screen.getByRole("button", { name: "运行预测" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText(/private/)).not.toBeInTheDocument();
  });

  it("keeps current input when returning from results", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse(successPayload));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.clear(screen.getByLabelText("样本名称"));
    await user.type(screen.getByLabelText("样本名称"), "sample-a");
    await user.click(screen.getByRole("button", { name: "确认参数" }));
    await user.click(screen.getByRole("button", { name: "运行预测" }));
    await screen.findByRole("heading", { name: "预测结果" });
    await user.click(screen.getByRole("button", { name: "返回编辑" }));

    expect(screen.getByLabelText("样本名称")).toHaveValue("sample-a");
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

function mockRejectedFetch() {
  const fetchMock = vi.fn<typeof fetch>();
  fetchMock.mockRejectedValue(new Error("offline"));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
