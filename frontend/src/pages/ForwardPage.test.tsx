import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LanguageSwitcher } from "../i18n/LanguageSwitcher";
import { LOCALE_STORAGE_KEY } from "../i18n/locale";
import { renderWithI18n } from "../test/renderWithI18n";
import { ForwardPage } from "./ForwardPage";

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

beforeEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Forward localized chip-count form", () => {
  it("renders default Chinese six-chip form, strict 4 through 8 options, and P1 through P12", async () => {
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    expect(screen.getByRole("heading", { name: "正向预测" })).toBeInTheDocument();
    expect(positionCells()).toHaveLength(6);
    expect(screen.getByText("P1/P2")).toBeInTheDocument();
    expect(screen.getByText("P11/P12")).toBeInTheDocument();
    expect(document.title).toBe("正向预测 | 药物浓度梯度芯片");

    for (let position = 1; position <= 6; position += 1) {
      expectWidthAttributes(leftWidthInput(position));
      expectWidthAttributes(rightWidthInput(position));
      expectDistanceAttributes(leftDistanceInput(position));
      expectDistanceAttributes(rightDistanceInput(position));
    }

    const options = within(chipCountSelect()).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["4", "5", "6", "7", "8"]);
  });

  it("switches core fields to English without clearing chip_count or modified inputs", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.selectOptions(chipCountSelect(), "8");
    await user.clear(leftWidthInput(7));
    await user.type(leftWidthInput(7), "0.125");
    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(screen.getByRole("heading", { name: "Forward Prediction" })).toBeInTheDocument();
    expect(chipCountSelect()).toHaveValue("8");
    expect(leftWidthInput(7)).toHaveValue(0.125);
    expect(screen.getByText("P15/P16")).toBeInTheDocument();
    expect(screen.getByText("Left Width mm")).toBeInTheDocument();
    expect(screen.getByText("Right Bend-to-Straight Distance mm")).toBeInTheDocument();
  });

  it("selecting 4 renders four positions and P1 through P8 only", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "芯片数量" }), "4");

    expect(positionCells()).toHaveLength(4);
    expect(screen.getByText("P7/P8")).toBeInTheDocument();
    expect(screen.queryByText("位置 5")).not.toBeInTheDocument();
    expect(screen.queryByText("P9/P10")).not.toBeInTheDocument();
  });

  it("keeps existing rows, creates independent defaults, and regenerates removed tail rows", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.selectOptions(chipCountSelect(), "8");
    await user.clear(leftWidthInput(7));
    await user.type(leftWidthInput(7), "0.125");
    expect(leftWidthInput(8)).toHaveValue(0.261);

    await user.selectOptions(chipCountSelect(), "5");
    expect(screen.queryByText("位置 6")).not.toBeInTheDocument();

    await user.selectOptions(chipCountSelect(), "8");
    expect(leftWidthInput(6)).toHaveValue(0.261);
    expect(leftWidthInput(7)).toHaveValue(0.261);
    expect(leftWidthInput(8)).toHaveValue(0.261);
    expect(chipTypeSelect(7)).toHaveValue("5to4");
    expect(chipTypeSelect(8)).toHaveValue("5to4");
  });

  it("restore example resets chip_count, six example rows, inlet mode, and transient state", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.selectOptions(chipCountSelect(), "4");
    await user.click(confirmButton());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "恢复官方示例" }));

    expect(chipCountSelect()).toHaveValue("6");
    expect(positionCells()).toHaveLength(6);
    expect(chipTypeSelect(1)).toHaveValue("5to4");
    expect(chipTypeSelect(6)).toHaveValue("3to1");
    expect(leftWidthInput(6)).toHaveValue(0.05);
    expect(screen.getByRole("radio", { name: "Inlet1=1, Inlet2=0" })).toBeChecked();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Forward localized workflow interactions", () => {
  it.each([
    ["0.04", "0.310"],
    ["0.040", "0.31"],
    ["0.041", "0.125"],
    ["0.1", "0.3"],
  ])("accepts legal width boundary values %s and %s", async (leftWidth, rightWidth) => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.clear(leftWidthInput(1));
    await user.type(leftWidthInput(1), leftWidth);
    await user.clear(rightWidthInput(1));
    await user.type(rightWidthInput(1), rightWidth);
    await user.click(confirmButton());

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    ["zh-CN", "左宽度必须在 0.04～0.31 mm 之间。"],
    ["en", "Left width must be between 0.04 and 0.31 mm."],
  ])("shows localized width validation in %s", async (locale, expected) => {
    const user = userEvent.setup();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await user.clear(leftWidthInput(1));
    await user.type(leftWidthInput(1), "0.039");
    await user.click(confirmButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("preserves an invalid width value and allows confirmation after correction", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await user.clear(leftWidthInput(1));
    await user.type(leftWidthInput(1), "0.311");
    await user.click(confirmButton());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(leftWidthInput(1)).toHaveValue(0.311);

    await user.clear(leftWidthInput(1));
    await user.type(leftWidthInput(1), "0.31");
    await user.click(confirmButton());

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps inlet choices mutually exclusive and sends the selected relation", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderForwardPage();

    const inlet1 = await screen.findByRole("radio", { name: "Inlet1=1, Inlet2=0" });
    const inlet2 = screen.getByRole("radio", { name: "Inlet1=0, Inlet2=1" });
    expect(inlet1).toBeChecked();

    await user.click(inlet2);
    await user.click(confirmButton());
    await user.click(runButton());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(request.inlet1).toBe(0);
    expect(request.inlet2).toBe(1);
  });

  it.each(["4", "5", "7", "8"])("allows confirming chip_count=%s but blocks prediction before API call", async (count) => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "芯片数量" }), count);
    await user.click(confirmButton());

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    expect(screen.getAllByText(/当前正式模型仅支持 6 个芯片/).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("submits chip_count=6 once and displays six concentration-only predictions", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderForwardPage();

    await user.click(await screen.findByRole("button", { name: "确认输入" }));
    await user.click(runButton());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("0.123457")).toBeInTheDocument();
    expect(screen.getByText("5.123457")).toBeInTheDocument();
    const responseText = document.body.textContent ?? "";
    expect(responseText).not.toMatch(/flow|seed|mean|std|ensemble/i);

    const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(request.chip_count).toBe(6);
    expect(request.chips).toHaveLength(6);
  });

  it("prevents duplicate prediction submits while loading", async () => {
    const user = userEvent.setup();
    let resolveForward: (response: Response) => void = () => undefined;
    const forwardPromise = new Promise<Response>((resolve) => {
      resolveForward = resolve;
    });
    const fetchMock = mockFetch(jsonResponse(statusReady), forwardPromise);
    renderForwardPage();

    await user.click(await screen.findByRole("button", { name: "确认输入" }));
    const run = runButton();
    await user.click(run);
    await user.click(run);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveForward(jsonResponse(successPayload()));
    expect(await screen.findByText("0.123457")).toBeInTheDocument();
  });

  it("keeps modified input, confirmation, result, and avoids duplicate forward calls when switching language", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderForwardPage();

    const sampleName = await screen.findByRole("textbox");
    await user.clear(sampleName);
    await user.type(sampleName, "sample-a");
    await user.click(confirmButton());
    await user.click(screen.getByRole("button", { name: "EN" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Prediction" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Run Prediction" }));
    await screen.findByText("0.123457");
    await user.click(screen.getByRole("button", { name: "中文" }));

    expect(screen.getByText("预测结果")).toBeInTheDocument();
    expect(screen.getByText("样本：DP 0")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("renders prediction rows using response.predictions length", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse(successPayload(3)));
    renderForwardPage();

    await user.click(await screen.findByRole("button", { name: "确认输入" }));
    await user.click(runButton());

    await screen.findByText("y3");
    expect(screen.queryByText("y4")).not.toBeInTheDocument();
  });
});

function renderForwardPage() {
  renderWithI18n(
    <MemoryRouter>
      <LanguageSwitcher />
      <ForwardPage />
    </MemoryRouter>,
  );
}

function chipCountSelect() {
  return screen.getByRole("combobox", { name: /芯片数量|Number of Chips/ });
}

function positionCells() {
  return screen.getAllByText((_, element) => element?.textContent?.match(/^(位置|Position) \d+$/) !== null);
}

function chipTypeSelect(position: number) {
  return screen.getByLabelText(new RegExp(`(位置|Position) ${position} (芯片类型|Chip Type)`));
}

function leftWidthInput(position: number) {
  return numericInputsForPosition(position)[0] as HTMLInputElement;
}

function rightWidthInput(position: number) {
  return numericInputsForPosition(position)[1] as HTMLInputElement;
}

function leftDistanceInput(position: number) {
  return numericInputsForPosition(position)[2] as HTMLInputElement;
}

function rightDistanceInput(position: number) {
  return numericInputsForPosition(position)[3] as HTMLInputElement;
}

function expectWidthAttributes(input: HTMLElement) {
  expect(input).toHaveAttribute("min", "0.04");
  expect(input).toHaveAttribute("max", "0.31");
  expect(input).toHaveAttribute("step", "0.001");
}

function expectDistanceAttributes(input: HTMLElement) {
  expect(input).not.toHaveAttribute("min");
  expect(input).not.toHaveAttribute("max");
  expect(input).toHaveAttribute("step", "1");
}

function numericInputsForPosition(position: number) {
  const inputs = screen.getAllByRole("spinbutton");
  const start = (position - 1) * 4;
  return inputs.slice(start, start + 4);
}

function confirmButton() {
  return screen.getByRole("button", { name: /确认输入|Confirm Inputs/ });
}

function runButton() {
  return screen.getByRole("button", { name: /运行预测|Run Prediction/ });
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
