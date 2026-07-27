import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Forward chip count form", () => {
  it("renders default six-chip form, strict 4 through 8 options, and P1 through P12", async () => {
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    expect(positionCells()).toHaveLength(6);
    expect(screen.getByText("P1/P2")).toBeInTheDocument();
    expect(screen.getByText("P11/P12")).toBeInTheDocument();

    const options = within(chipCountSelect()).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["4", "5", "6", "7", "8"]);
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

  it("selecting 8 renders eight positions and P1 through P16", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "芯片数量" }), "8");

    expect(positionCells()).toHaveLength(8);
    expect(screen.getByText("P15/P16")).toBeInTheDocument();
  });

  it("keeps existing rows and adds the unified default row when increasing from 6 to 7", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.clear(leftWidthInput(1));
    await user.type(leftWidthInput(1), "9.99");
    await user.selectOptions(chipCountSelect(), "7");

    expect(leftWidthInput(1)).toHaveValue(9.99);
    expect(chipTypeSelect(7)).toHaveValue("5to4");
    expect(leftWidthInput(7)).toHaveValue(0.261);
    expect(rightWidthInput(7)).toHaveValue(0.138);
    expect(leftDistanceInput(7)).toHaveValue(31);
    expect(rightDistanceInput(7)).toHaveValue(25);
  });

  it("creates independent default rows when increasing from 6 to 8", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.selectOptions(chipCountSelect(), "8");
    await user.clear(leftWidthInput(7));
    await user.type(leftWidthInput(7), "7.77");

    expect(leftWidthInput(7)).toHaveValue(7.77);
    expect(leftWidthInput(8)).toHaveValue(0.261);
    expect(chipTypeSelect(7)).toHaveValue("5to4");
    expect(chipTypeSelect(8)).toHaveValue("5to4");
  });

  it("drops removed tail rows and regenerates defaults when increasing again", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.selectOptions(chipCountSelect(), "8");
    await user.clear(leftWidthInput(6));
    await user.type(leftWidthInput(6), "8.88");
    await user.selectOptions(chipCountSelect(), "5");
    expect(screen.queryByText("位置 6")).not.toBeInTheDocument();

    await user.selectOptions(chipCountSelect(), "8");
    expect(leftWidthInput(6)).toHaveValue(0.261);
    expect(leftWidthInput(7)).toHaveValue(0.261);
    expect(leftWidthInput(8)).toHaveValue(0.261);
  });

  it("restore example resets chip_count, six example rows, inlet mode, and transient state", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse({ error: { code: "UNSUPPORTED_CHIP_COUNT" } }, 422));
    renderForwardPage();

    await waitFor(() => expect(chipCountSelect()).toHaveValue("6"));
    await user.selectOptions(chipCountSelect(), "4");
    await user.click(confirmButton());
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /恢复|鎭/ }));

    expect(chipCountSelect()).toHaveValue("6");
    expect(positionCells()).toHaveLength(6);
    expect(chipTypeSelect(1)).toHaveValue("5to4");
    expect(chipTypeSelect(6)).toHaveValue("3to1");
    expect(leftWidthInput(6)).toHaveValue(0.05);
    expect(screen.getByRole("radio", { name: "inlet1=1, inlet2=0" })).toBeChecked();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Forward workflow interactions", () => {
  it("keeps inlet high-concentration choices mutually exclusive and sends the selected relation", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderForwardPage();

    const inlet1 = await screen.findByRole("radio", { name: "inlet1=1, inlet2=0" });
    const inlet2 = screen.getByRole("radio", { name: "inlet1=0, inlet2=1" });
    expect(inlet1).toBeChecked();

    await user.click(inlet2);
    expect(inlet1).not.toBeChecked();
    expect(inlet2).toBeChecked();
    await user.click(confirmButton());
    await user.click(runButton());

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(request.inlet1).toBe(0);
    expect(request.inlet2).toBe(1);
  });

  it("does not call forward API for invalid numeric input", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await user.clear(leftWidthInput(1));
    await user.click(confirmButton());

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(["4", "5", "7", "8"])("allows confirming chip_count=%s but blocks prediction before API call", async (count) => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady));
    renderForwardPage();

    await user.selectOptions(await screen.findByRole("combobox", { name: "芯片数量" }), count);
    await user.click(confirmButton());

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    expect(screen.getAllByText(/正式/).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("submits chip_count=6 once and displays six concentration-only predictions", async () => {
    const user = userEvent.setup();
    const fetchMock = mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderForwardPage();

    await user.click(await screen.findByRole("button", { name: /纭|确/ }));
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

    await user.click(await screen.findByRole("button", { name: /纭|确/ }));
    const run = runButton();
    await user.click(run);
    await user.click(run);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    resolveForward(jsonResponse(successPayload()));
    expect(await screen.findByText("0.123457")).toBeInTheDocument();
  });

  it("keeps modified visible input when returning from confirmation and results", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse(successPayload()));
    renderForwardPage();

    const sampleName = await screen.findByRole("textbox");
    await user.clear(sampleName);
    await user.type(sampleName, "sample-a");
    await user.click(confirmButton());
    await user.click(screen.getByRole("button", { name: /返回编辑|杩斿洖/ }));
    expect(screen.getByRole("textbox")).toHaveValue("sample-a");

    await user.click(confirmButton());
    await user.click(runButton());
    await screen.findByText("0.123457");
    await user.click(screen.getByRole("button", { name: /返回编辑|杩斿洖/ }));
    expect(screen.getByRole("textbox")).toHaveValue("sample-a");
  });

  it("renders prediction rows using response.predictions length", async () => {
    const user = userEvent.setup();
    mockFetch(jsonResponse(statusReady), jsonResponse(successPayload(3)));
    renderForwardPage();

    await user.click(await screen.findByRole("button", { name: /纭|确/ }));
    await user.click(runButton());

    await screen.findByText("y3");
    expect(screen.queryByText("y4")).not.toBeInTheDocument();
  });
});

function renderForwardPage() {
  render(
    <MemoryRouter>
      <ForwardPage />
    </MemoryRouter>,
  );
}

function chipCountSelect() {
  return screen.getByRole("combobox", { name: "芯片数量" });
}

function positionCells() {
  return screen.getAllByText((_, element) => element?.textContent?.match(/^位置 \d+$/) !== null);
}

function chipTypeSelect(position: number) {
  return screen.getByLabelText(`位置 ${position} 芯片类型`);
}

function leftWidthInput(position: number) {
  return numericInputsForPosition(position)[0];
}

function rightWidthInput(position: number) {
  return numericInputsForPosition(position)[1];
}

function leftDistanceInput(position: number) {
  return numericInputsForPosition(position)[2];
}

function rightDistanceInput(position: number) {
  return numericInputsForPosition(position)[3];
}

function numericInputsForPosition(position: number) {
  const inputs = screen.getAllByRole("spinbutton");
  const start = (position - 1) * 4;
  return inputs.slice(start, start + 4);
}

function confirmButton() {
  return screen.getByRole("button", { name: /纭|确/ });
}

function runButton() {
  return screen.getByRole("button", { name: /运行|杩愯/ });
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
