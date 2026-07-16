export interface ChipFormRow {
  position: number;
  point_left: string;
  point_right: string;
  chip_type: string;
  left_width_mm: string;
  right_width_mm: string;
  left_bend_straight_distance_mm: string;
  right_bend_straight_distance_mm: string;
}

export interface ForwardFormState {
  sample_name: string;
  inletMode: "inlet1" | "inlet2";
  chips: ChipFormRow[];
}

export const CHIP_TYPE_OPTIONS = Array.from({ length: 6 }, (_, leftIndex) =>
  Array.from({ length: 6 }, (_, rightIndex) => `${leftIndex + 1}to${rightIndex + 1}`),
).flat();

export const EXAMPLE_FORM: ForwardFormState = {
  sample_name: "DP 0",
  inletMode: "inlet1",
  chips: [
    {
      position: 1,
      point_left: "P1",
      point_right: "P2",
      chip_type: "5to4",
      left_width_mm: "0.261",
      right_width_mm: "0.138",
      left_bend_straight_distance_mm: "31",
      right_bend_straight_distance_mm: "25",
    },
    {
      position: 2,
      point_left: "P3",
      point_right: "P4",
      chip_type: "4to2",
      left_width_mm: "0.089",
      right_width_mm: "0.04",
      left_bend_straight_distance_mm: "25",
      right_bend_straight_distance_mm: "13",
    },
    {
      position: 3,
      point_left: "P5",
      point_right: "P6",
      chip_type: "1to6",
      left_width_mm: "0.212",
      right_width_mm: "0.236",
      left_bend_straight_distance_mm: "7",
      right_bend_straight_distance_mm: "31",
    },
    {
      position: 4,
      point_left: "P7",
      point_right: "P8",
      chip_type: "2to4",
      left_width_mm: "0.31",
      right_width_mm: "0.163",
      left_bend_straight_distance_mm: "13",
      right_bend_straight_distance_mm: "25",
    },
    {
      position: 5,
      point_left: "P9",
      point_right: "P10",
      chip_type: "6to3",
      left_width_mm: "0.187",
      right_width_mm: "0.285",
      left_bend_straight_distance_mm: "37",
      right_bend_straight_distance_mm: "19",
    },
    {
      position: 6,
      point_left: "P11",
      point_right: "P12",
      chip_type: "3to1",
      left_width_mm: "0.05",
      right_width_mm: "0.114",
      left_bend_straight_distance_mm: "13",
      right_bend_straight_distance_mm: "7",
    },
  ],
};

export function cloneExampleForm(): ForwardFormState {
  return {
    ...EXAMPLE_FORM,
    chips: EXAMPLE_FORM.chips.map((chip) => ({ ...chip })),
  };
}

export function emptyEditableForm(previous: ForwardFormState): ForwardFormState {
  return {
    sample_name: "",
    inletMode: previous.inletMode,
    chips: previous.chips.map((chip) => ({
      ...chip,
      chip_type: "1to1",
      left_width_mm: "",
      right_width_mm: "",
      left_bend_straight_distance_mm: "",
      right_bend_straight_distance_mm: "",
    })),
  };
}
