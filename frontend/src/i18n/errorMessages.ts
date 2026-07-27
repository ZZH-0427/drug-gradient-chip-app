import type { ApiClientError } from "../api/client";
import type { ApiErrorResponse } from "../api/types";
import type { I18nContextValue } from "./context";

export function apiClientErrorMessage(error: ApiClientError, t: I18nContextValue["t"]): string {
  switch (error.kind) {
    case "validation":
      return t("errors.validation");
    case "unsupported_chip_count":
      return t("errors.unsupported_chip_count");
    case "model_unavailable":
      return t("errors.model_unavailable");
    case "inference_failure":
      return t("errors.inference_failure");
    case "reverse_busy":
      return t("errors.reverse_busy");
    case "reverse_not_found":
      return t("errors.reverse_not_found");
    case "reverse_not_cancellable":
      return t("errors.reverse_not_cancellable");
    case "reverse_failed":
      return t("errors.reverse_failed");
    case "network":
      return t("errors.network");
    case "unexpected":
    default:
      return t("errors.unexpected");
  }
}

export function apiErrorCodeMessage(error: ApiErrorResponse["error"] | undefined, t: I18nContextValue["t"]): string {
  switch (error?.code) {
    case "REVERSE_TASK_TIMEOUT":
      return t("errors.reverse_timeout");
    case "REVERSE_MODEL_UNAVAILABLE":
      return t("errors.reverse_model_unavailable");
    case "REVERSE_TASK_FAILED":
      return t("errors.reverse_failed");
    default:
      return t("errors.reverse_failed");
  }
}
