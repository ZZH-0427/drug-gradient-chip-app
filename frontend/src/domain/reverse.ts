import type { ReverseDesignRequest } from "../api/types";

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

export function validateReverseRequest(payload: ReverseDesignRequest): string[] {
  const errors: string[] = [];
  if (!Number.isFinite(payload.inlet1) || !Number.isFinite(payload.inlet2)) {
    errors.push("入口浓度必须为有限数值。");
  }
  if (Math.abs(payload.inlet1 - payload.inlet2) < 1e-12) {
    errors.push("入口1和入口2不能相同。");
  }
  if (payload.target_concentrations.length !== REVERSE_TARGET_COUNT) {
    errors.push("反向设计需要恰好6个目标浓度。");
  }
  payload.target_concentrations.forEach((value, index) => {
    if (!Number.isFinite(value)) {
      errors.push(`y${index + 1}目标浓度必须为有限数值。`);
    }
  });
  return errors;
}
