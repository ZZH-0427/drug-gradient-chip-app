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
  concentration: number;
}

export interface ForwardPredictionResponse {
  sample_name: string;
  inlets: Record<string, number>;
  chip_count: number;
  predictions: ForwardPredictionItem[];
}

export interface ModelStatusResponse {
  ready: boolean;
  model_name: string;
  supported_chip_counts: number[];
  public_output: string;
  device: string;
  forward?: {
    ready?: boolean;
    supported_chip_counts?: number[];
    output?: string;
    execution_mode?: string;
  };
  reverse?: {
    ready?: boolean;
    supported_chip_counts?: number[];
    execution_mode?: string;
    max_concurrent_tasks?: number;
  };
}

export interface ReverseDesignRequest {
  inlet1: number;
  inlet2: number;
  target_concentrations: number[];
}

export interface ReverseTaskCreatedResponse {
  task_id: string;
  status: ReverseTaskStatus;
}

export type ReverseTaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface ReverseDesignChipResult {
  position: number;
  point_labels: string[];
  chip_type: string;
  left_width_mm: number;
  right_width_mm: number;
  left_bend_class: number;
  right_bend_class: number;
  left_distance_mm: number;
  right_distance_mm: number;
  target_concentration: number;
  predicted_concentration: number;
  absolute_error: number;
}

export interface ReverseDesignResult {
  inlet1: number;
  inlet2: number;
  target_concentrations: number[];
  chips: ReverseDesignChipResult[];
  metrics: {
    mae: number;
    rmse: number;
    maxae: number;
    spearman: number;
    internal_screening_pass: boolean;
    selected_restart: number;
  };
  warnings: string[];
  notes: string[];
}

export interface ReverseTaskStatusResponse {
  task_id: string;
  status: ReverseTaskStatus;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  elapsed_seconds?: number | null;
  result?: ReverseDesignResult | null;
  error?: { code: string; message: string } | null;
  warnings: string[];
}

export type ChatLanguage = "zh-CN" | "en" | "en-US";
export type ChatState = "idle" | "collecting" | "ready_for_confirmation" | "running" | "completed" | "error";
export type ChatIntent =
  | "unknown"
  | "start_forward"
  | "start_reverse"
  | "set_chip_count"
  | "set_inlet"
  | "set_chip_parameter"
  | "set_target_concentration"
  | "show_parameters"
  | "confirm"
  | "run_prediction"
  | "cancel"
  | "reset"
  | "help"
  | "switch_language";

export interface ChatMessageRequest {
  session_id?: string | null;
  message: string;
  language: ChatLanguage;
}

export interface ChatError {
  code: string;
  message: string;
}

export interface ChatConfirmation {
  mode: "idle" | "forward" | "reverse";
  summary: ParameterSummary;
}

export type ParameterSummary = Record<string, unknown>;

export interface ChatMessageResponse {
  session_id: string;
  state: ChatState;
  intent: ChatIntent;
  assistant_message: string;
  missing_fields: string[];
  parameter_summary: ParameterSummary;
  confirmation?: ChatConfirmation | null;
  forward_prediction?: ForwardPredictionResponse | null;
  reverse_task?: ReverseTaskCreatedResponse | null;
  error?: ChatError | null;
}

export interface ApiErrorResponse {
  error?: {
    code?: string;
    message?: string;
  };
  detail?: unknown;
}
