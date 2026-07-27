import type {
  ApiErrorResponse,
  ForwardPredictionRequest,
  ForwardPredictionResponse,
  ModelStatusResponse,
  ReverseDesignRequest,
  ReverseTaskCreatedResponse,
  ReverseTaskStatusResponse,
} from "./types";
import { resolveApiBaseUrl } from "./baseUrl";

const API_BASE_URL = resolveApiBaseUrl({
  configuredUrl: import.meta.env.VITE_API_BASE_URL,
  isDevelopment: import.meta.env.DEV,
});

export class ApiClientError extends Error {
  constructor(
    public readonly kind:
      | "validation"
      | "unsupported_chip_count"
      | "model_unavailable"
      | "inference_failure"
      | "reverse_busy"
      | "reverse_not_found"
      | "reverse_not_cancellable"
      | "reverse_failed"
      | "network"
      | "unexpected",
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

export async function getModelStatus(): Promise<ModelStatusResponse> {
  return request<ModelStatusResponse>("/api/v1/model-status", { method: "GET" });
}

export async function runForwardPrediction(
  payload: ForwardPredictionRequest,
): Promise<ForwardPredictionResponse> {
  return request<ForwardPredictionResponse>("/api/v1/forward", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function createReverseTask(
  payload: ReverseDesignRequest,
): Promise<ReverseTaskCreatedResponse> {
  return request<ReverseTaskCreatedResponse>("/api/v1/reverse-tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function getReverseTask(taskId: string): Promise<ReverseTaskStatusResponse> {
  return request<ReverseTaskStatusResponse>(`/api/v1/reverse-tasks/${taskId}`, { method: "GET" });
}

export async function cancelReverseTask(taskId: string): Promise<ReverseTaskStatusResponse> {
  return request<ReverseTaskStatusResponse>(`/api/v1/reverse-tasks/${taskId}`, { method: "DELETE" });
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiClientError("network", "Network request failed.");
  }

  const payload = await readJson(response);
  if (!response.ok) {
    throw mapError(response.status, payload);
  }

  if (!payload || typeof payload !== "object") {
    throw new ApiClientError("unexpected", "Unexpected response format.", response.status);
  }
  return payload as T;
}

async function readJson(response: Response): Promise<ApiErrorResponse | unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function mapError(status: number, payload: ApiErrorResponse | unknown): ApiClientError {
  const known = payload && typeof payload === "object" ? (payload as ApiErrorResponse).error : undefined;
  if (known?.code === "UNSUPPORTED_CHIP_COUNT") {
    return new ApiClientError("unsupported_chip_count", "Unsupported chip count.", status);
  }
  if (known?.code === "REVERSE_TASK_BUSY") {
    return new ApiClientError("reverse_busy", "Reverse task is busy.", status);
  }
  if (known?.code === "REVERSE_TASK_NOT_FOUND") {
    return new ApiClientError("reverse_not_found", "Reverse task was not found.", status);
  }
  if (known?.code === "REVERSE_TASK_NOT_CANCELLABLE") {
    return new ApiClientError("reverse_not_cancellable", "Reverse task cannot be cancelled.", status);
  }
  if (known?.code?.startsWith("REVERSE_")) {
    return new ApiClientError("reverse_failed", "Reverse task failed.", status);
  }
  if (status === 422) {
    return new ApiClientError("validation", "Validation failed.", status);
  }
  if (status === 503) {
    return new ApiClientError("model_unavailable", "Model unavailable.", status);
  }
  if (status === 500) {
    return new ApiClientError("inference_failure", "Inference failed.", status);
  }
  if (known?.code) {
    return new ApiClientError("unexpected", "Unexpected API error.", status);
  }
  return new ApiClientError("unexpected", "Unexpected response format.", status);
}
