import type { ReverseDesignRequest } from "../api/types";
import type { I18nContextValue } from "../i18n/context";

export const REVERSE_TARGET_COUNT = 6;
export const DEFAULT_REVERSE_REQUEST: ReverseDesignRequest = {
  inlet1: 0,
  inlet2: 1,
  target_concentrations: [0.08, 0.14, 0.25, 0.38, 0.48, 0.58],
};

export function cloneDefaultReverseRequest(): ReverseDesignRequest {
  return {
    inlet1: DEFAULT_REVERSE_REQUEST.inlet1,
    inlet2: DEFAULT_REVERSE_REQUEST.inlet2,
    target_concentrations: [...DEFAULT_REVERSE_REQUEST.target_concentrations],
  };
}

export function validateReverseRequest(
  payload: ReverseDesignRequest,
  t: I18nContextValue["t"],
): string[] {
  const errors: string[] = [];
  if (!Number.isFinite(payload.inlet1) || !Number.isFinite(payload.inlet2)) {
    errors.push(t("reverseValidation.finiteInlets"));
  }
  if (Math.abs(payload.inlet1 - payload.inlet2) < 1e-12) {
    errors.push(t("reverseValidation.distinctInlets"));
  }
  if (payload.target_concentrations.length !== REVERSE_TARGET_COUNT) {
    errors.push(t("reverseValidation.targetCount", { count: REVERSE_TARGET_COUNT }));
  }
  payload.target_concentrations.forEach((value, index) => {
    if (!Number.isFinite(value)) {
      errors.push(t("reverseValidation.finiteTarget", { index: index + 1 }));
    }
  });
  return errors;
}
