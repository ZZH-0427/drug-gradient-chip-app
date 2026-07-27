import type { ForwardPredictionRequest } from "../api/types";
import type { I18nContextValue } from "../i18n/context";
import {
  FORWARD_WIDTH_MAX,
  FORWARD_WIDTH_MIN,
  MAX_CHIP_COUNT,
  MIN_CHIP_COUNT,
} from "./forward";
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
const widthFields = ["left_width_mm", "right_width_mm"] as const;

export function validateForwardForm(form: ForwardFormState, t: I18nContextValue["t"]): ValidationResult {
  const errors: string[] = [];
  const sampleName = form.sample_name.trim();
  if (!sampleName) {
    errors.push(t("forward.sampleRequired"));
  }
  if (form.chip_count < MIN_CHIP_COUNT || form.chip_count > MAX_CHIP_COUNT) {
    errors.push(t("forward.chipCountRange", { min: MIN_CHIP_COUNT, max: MAX_CHIP_COUNT }));
  }
  if (form.chips.length !== form.chip_count) {
    errors.push(t("forward.chipLengthMismatch"));
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
        errors.push(t("forward.numericIncomplete", { position: chip.position }));
        break;
      }
    }
    for (const field of widthFields) {
      const parsedWidth = parseFinite(chip[field]);
      if (
        parsedWidth === undefined ||
        parsedWidth < FORWARD_WIDTH_MIN ||
        parsedWidth > FORWARD_WIDTH_MAX ||
        !hasValidWidthPrecision(chip[field])
      ) {
        errors.push(
          field === "left_width_mm" ? t("forward.leftWidthRange") : t("forward.rightWidthRange"),
        );
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

function hasValidWidthPrecision(value: string): boolean {
  const normalized = value.trim();
  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(normalized)) {
    return false;
  }
  const fraction = normalized.split(".")[1] ?? "";
  return fraction.replace(/0+$/, "").length <= 3;
}
