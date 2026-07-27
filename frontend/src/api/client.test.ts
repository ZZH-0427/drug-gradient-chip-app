import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, runForwardPrediction } from "./client";

const request = {
  sample_name: "DP 0",
  chip_count: 6,
  inlet1: 1,
  inlet2: 0,
  chips: Array.from({ length: 6 }, (_, index) => ({
    position: index + 1,
    chip_type: "5to4",
    left_width_mm: 0.261,
    right_width_mm: 0.138,
    left_bend_straight_distance_mm: 31,
    right_bend_straight_distance_mm: 25,
  })),
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API error mapping", () => {
  it.each([
    [422, { error: { code: "VALIDATION_ERROR", message: "C:\\private\\trace" } }, "validation"],
    [422, { error: { code: "UNSUPPORTED_CHIP_COUNT", message: "D:\\model\\checkpoint.pt" } }, "unsupported_chip_count"],
    [503, { error: { code: "MODEL_UNAVAILABLE", message: "Traceback" } }, "model_unavailable"],
    [500, { error: { code: "INFERENCE_FAILURE", message: "D:\\pytorch_geometric-master" } }, "inference_failure"],
    [418, { error: { code: "SOMETHING_NEW", message: "C:\\secret" } }, "unexpected"],
  ] as const)("maps HTTP %s error safely to %s", async (status, body, kind) => {
    mockFetch(jsonResponse(body, status));

    const error = await captureError();

    expect(error).toMatchObject({ name: "ApiClientError", kind, status });
    expect(error.message).not.toMatch(/Traceback|checkpoint|pytorch_geometric-master|[A-Z]:\\/i);
  });

  it("maps network failures safely", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(new Error("offline")));

    await expect(runForwardPrediction(request)).rejects.toMatchObject({
      name: "ApiClientError",
      kind: "network",
    });
  });

  it("maps malformed success payload as unexpected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response("", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(runForwardPrediction(request)).rejects.toMatchObject({
      name: "ApiClientError",
      kind: "unexpected",
    });
  });

  it("does not collapse unsupported chip count into the generic validation message", async () => {
    mockFetch(jsonResponse({ error: { code: "UNSUPPORTED_CHIP_COUNT" } }, 422));
    const unsupported = await captureError();

    mockFetch(jsonResponse({ error: { code: "VALIDATION_ERROR" } }, 422));
    const validation = await captureError();

    expect(unsupported.kind).toBe("unsupported_chip_count");
    expect(validation.kind).toBe("validation");
    expect(unsupported.message).not.toBe(validation.message);
  });
});

async function captureError() {
  try {
    await runForwardPrediction(request);
  } catch (error) {
    return error as ApiClientError;
  }
  throw new Error("Expected request to fail.");
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
