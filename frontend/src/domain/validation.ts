import type { ForwardPredictionRequest } from "../api/types";
import { MAX_CHIP_COUNT, MIN_CHIP_COUNT } from "./forward";
import type { ForwardFormState } from "./forward";

export interface ValidationResult {
  payload?: ForwardPredictionRequest;
  errors: string[];
}

type NumericChipField =
  | "left_width_mm"
  | "right_width_mm"
  | "left_bend_straight_distance_mm"
  | "right_bend_straight_distance_mm";

const numericFields: NumericChipField[] = [
  "left_width_mm",
  "right_width_mm",
  "left_bend_straight_distance_mm",
  "right_bend_straight_distance_mm",
];

export function validateForwardForm(form: ForwardFormState): ValidationResult {
  const errors: string[] = [];
  const sampleName = form.sample_name.trim();
  if (!sampleName) {
    errors.push("样本名称不能为空。");
  }
  if (form.chip_count < MIN_CHIP_COUNT || form.chip_count > MAX_CHIP_COUNT) {
    errors.push("芯片数量必须在4到8之间。");
  }
  if (form.chips.length !== form.chip_count) {
    errors.push("芯片位置数量必须与芯片数量一致。");
  }

  const chips = form.chips.map((chip) => {
    const parsed = {
      position: chip.position,
      chip_type: chip.chip_type,
      left_width_mm: parseFinite(chip.left_width_mm),
      right_width_mm: parseFinite(chip.right_width_mm),
      left_bend_straight_distance_mm: parseFinite(chip.left_bend_straight_distance_mm),
      right_bend_straight_distance_mm: parseFinite(chip.right_bend_straight_distance_mm),
    };

    for (const field of numericFields) {
      if (parseFinite(chip[field]) === undefined) {
        errors.push(`位置 ${chip.position} 的数值参数不完整或不是有限数字。`);
        break;
      }
    }
    return parsed;
  });

  if (errors.length > 0) {
    return { errors };
  }

  return {
    errors: [],
    payload: {
      sample_name: sampleName,
      chip_count: form.chip_count,
      inlet1: form.inletMode === "inlet1" ? 1 : 0,
      inlet2: form.inletMode === "inlet2" ? 1 : 0,
      chips: chips.map((chip) => ({
        position: chip.position,
        chip_type: chip.chip_type,
        left_width_mm: chip.left_width_mm ?? 0,
        right_width_mm: chip.right_width_mm ?? 0,
        left_bend_straight_distance_mm: chip.left_bend_straight_distance_mm ?? 0,
        right_bend_straight_distance_mm: chip.right_bend_straight_distance_mm ?? 0,
      })),
    },
  };
}

function parseFinite(value: string): number | undefined {
  if (!value.trim()) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
