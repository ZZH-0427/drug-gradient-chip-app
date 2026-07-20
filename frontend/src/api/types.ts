export interface ForwardChipInput {
  position: number;
  chip_type: string;
  left_width_mm: number;
  right_width_mm: number;
  left_bend_straight_distance_mm: number;
  right_bend_straight_distance_mm: number;
}

export interface ForwardPredictionRequest {
  sample_name: string;
  chip_count: number;
  inlet1: number;
  inlet2: number;
  chips: ForwardChipInput[];
}

export interface ForwardPredictionItem {
  position: number;
  point: string;
  chip_type: string;
  mean: number;
  std: number;
  seed_values: Record<string, number>;
}

export interface ForwardPredictionResponse {
  sample_name: string;
  inlets: Record<string, number>;
  ensemble_seeds: number[];
  predictions: ForwardPredictionItem[];
}

export interface ModelStatusResponse {
  ready: boolean;
  model_name: string;
  ensemble_size: number;
  seeds: number[];
  device: string;
}

export interface ApiErrorResponse {
  error?: {
    code?: string;
    message?: string;
  };
  detail?: unknown;
}
