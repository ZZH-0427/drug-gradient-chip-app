import type {
  ApiErrorResponse,
  ForwardPredictionRequest,
  ForwardPredictionResponse,
  ModelStatusResponse,
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

export class ApiClientError extends Error {
  constructor(
    public readonly kind:
      | "validation"
      | "model_unavailable"
      | "inference_failure"
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

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiClientError("network", "后端服务不可用，请确认 FastAPI 已启动。");
  }

  const payload = await readJson(response);
  if (!response.ok) {
    throw mapError(response.status, payload);
  }

  if (!payload || typeof payload !== "object") {
    throw new ApiClientError("unexpected", "后端返回格式异常。", response.status);
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
  if (status === 422) {
    return new ApiClientError("validation", "参数验证失败，请检查芯片参数。", status);
  }
  if (status === 503) {
    return new ApiClientError("model_unavailable", "正向模型暂不可用，请检查模型资产和后端状态。", status);
  }
  if (status === 500) {
    return new ApiClientError("inference_failure", "正向预测执行失败，请稍后重试。", status);
  }
  const known = payload && typeof payload === "object" ? (payload as ApiErrorResponse).error : undefined;
  if (known?.code) {
    return new ApiClientError("unexpected", "后端返回了无法处理的错误。", status);
  }
  return new ApiClientError("unexpected", "后端返回格式异常。", status);
}
