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

function successPayload(length = 6) {
  return {
    sample_name: "DP 0",
    inlets: { inlet1: 1, inlet2: 0 },
    ensemble_seeds: [42, 52, 62, 72, 82],
    predictions: Array.from({ length }, (_, index) => ({
      position: index + 1,
      point: `y${index + 1}`,
      chip_type: ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1"][index] ?? "1to1",
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
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App navigation", () => {
  it("renders only the forward entry on the home page", () => {
    renderApp("/");

    expect(screen.getByRole("heading", { name: "药物浓度梯度芯片预测系统" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "正向预测" })).toBeInTheDocument();
    expect(screen.queryByText("反向预测")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "反向预测" })).not.toBeInTheDocument();
  });

  it("shows not found for /reverse", () => {
    renderApp("/reverse");

    expect(screen.getByRole("heading", { name: "页面不存在" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回首页" })).toBeInTheDocument();
  });
});

describe("Forward workflow", () => {
  it("renders default six-chip form, generated point labels, chip options, and mutually exclusive inlet choices", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    expect(screen.getByRole("combobox", { name: "芯片数量" })).toHaveValue("6");
    expect(screen.getByLabelText("芯片数量摘要")).toHaveTextContent("芯片数量：6");
    expect(screen.getByLabelText("芯片数量摘要")).toHaveTextContent("位置数量：6");
    expect(screen.getByLabelText("芯片数量摘要")).toHaveTextContent("点位数量：12");
    expect(screen.getAllByText(/^位置 \d+$/)).toHaveLength(6);
    expect(screen.getByText("P1/P2")).toBeInTheDocument();
    expect(screen.getByText("P11/P12")).toBeInTheDocument();

    const countOptions = within(screen.getByRole("combobox", { name: "芯片数量" })).getAllByRole("option");
    expect(countOptions.map((option) => option.textContent)).toEqual(["4", "5", "6", "7", "8", "9", "10"]);

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

  it("selecting 4 renders four positions and P1 through P8 only", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "4");

    expect(screen.getAllByText(/^位置 \d+$/)).toHaveLength(4);
    expect(screen.getByText("P7/P8")).toBeInTheDocument();
    expect(screen.queryByText("位置 5")).not.toBeInTheDocument();
    expect(screen.queryByText("P9/P10")).not.toBeInTheDocument();
  });

  it("selecting 10 renders ten positions and P1 through P20", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "10");

    expect(screen.getAllByText(/^位置 \d+$/)).toHaveLength(10);
    expect(screen.getByText("P19/P20")).toBeInTheDocument();
  });

  it("preserves visible rows when increasing count and creates new default rows", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.clear(screen.getByLabelText("位置 1 左宽度"));
    await user.type(screen.getByLabelText("位置 1 左宽度"), "9.99");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "8");

    expect(screen.getByLabelText("位置 1 左宽度")).toHaveValue(9.99);
    expect(screen.getByLabelText("位置 7 左宽度")).toHaveValue(null);
    expect(screen.getByLabelText("位置 8 右弯曲直道距离")).toHaveValue(null);
    expect(screen.getByLabelText("位置 7 芯片类型")).toHaveValue("1to1");
  });

  it("drops removed rows and does not restore their old data when increasing again", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "8");
    await user.clear(screen.getByLabelText("位置 6 左宽度"));
    await user.type(screen.getByLabelText("位置 6 左宽度"), "8.88");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "5");

    expect(screen.getAllByText(/^位置 \d+$/)).toHaveLength(5);
    expect(screen.queryByLabelText("位置 6 左宽度")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "8");
    expect(screen.getByLabelText("位置 6 左宽度")).toHaveValue(null);
    expect(screen.getByLabelText("位置 6 芯片类型")).toHaveValue("1to1");
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

  it("opens confirmation without calling API, then submits chip_count=6 once and shows results", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
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

    const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(request.chip_count).toBe(6);
    expect(request.chips).toHaveLength(6);
  });

  it("does not call forward API for non-six chip counts", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "4");
    await user.click(screen.getByRole("button", { name: "确认参数" }));

    expect(screen.getByRole("dialog", { name: "确认正向预测参数" })).toBeInTheDocument();
    expect(screen.getAllByText("当前模型仅支持6个芯片。其他芯片数量将在可变节点模型接入后开放。")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "运行预测" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows dedicated message for backend unsupported chip count error", async () => {
    const user = userEvent.setup();
    mockFetch(
      jsonResponse(statusReady),
      jsonResponse({ error: { code: "UNSUPPORTED_CHIP_COUNT", message: "C:\\private\\trace" } }, 422),
    );
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.click(screen.getByRole("button", { name: "确认参数" }));
    await user.click(screen.getByRole("button", { name: "运行预测" }));

    expect(await screen.findByText("当前模型仅支持6个芯片。其他芯片数量将在可变节点模型接入后开放。")).toBeInTheDocument();
    expect(screen.queryByText(/private/)).not.toBeInTheDocument();
  });

  it("renders prediction results using the response length", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse(successPayload(3)));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.click(screen.getByRole("button", { name: "确认参数" }));
    await user.click(screen.getByRole("button", { name: "运行预测" }));

    await screen.findByRole("heading", { name: "预测结果" });
    expect(screen.getByText("y1")).toBeInTheDocument();
    expect(screen.getByText("y3")).toBeInTheDocument();
    expect(screen.queryByText("y4")).not.toBeInTheDocument();
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

    resolveForward(jsonResponse(successPayload()));
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

  it("keeps current visible input when returning from results", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
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

  it("restore example resets chip_count to 6 and current example values", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderApp("/forward");

    await screen.findByText("模型已就绪，ensemble=5");
    await user.selectOptions(screen.getByRole("combobox", { name: "芯片数量" }), "10");
    await user.clear(screen.getByLabelText("样本名称"));
    await user.type(screen.getByLabelText("样本名称"), "changed");
    await user.click(screen.getByRole("button", { name: "恢复示例" }));

    expect(screen.getByRole("combobox", { name: "芯片数量" })).toHaveValue("6");
    expect(screen.getByLabelText("样本名称")).toHaveValue("DP 0");
    expect(screen.getAllByText(/^位置 \d+$/)).toHaveLength(6);
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
