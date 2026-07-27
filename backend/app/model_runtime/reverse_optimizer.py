from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import ForwardModelSettings
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.model_runtime import reverse_engine


@dataclass(frozen=True)
class ReverseOptimizationParameters:
    steps: int = 1200
    refine_steps: int = 300
    restarts: int = 4
    seed: int = 42
    learning_rate: float = 0.025
    temperature_start: float = 2.0
    temperature_end: float = 0.15
    lambda_mae: float = 0.10
    lambda_width_center: float = 0.0005
    lambda_bend_complexity: float = 0.0003
    lambda_entropy: float = 0.0005
    min_mean_flow: float = 0.0
    screening_mae: float = 0.02
    screening_rmse: float = 0.03
    screening_maxae: float = 0.05
    screening_spearman: float = 0.95
    target_recommended_min: float = 0.10
    target_recommended_max: float = 0.95
    log_every: int = 0


def _resolve_checkpoint(settings: ForwardModelSettings | None = None) -> Path:
    resolved = settings or ForwardModelSettings.from_env()
    resolved.validate_assets()
    return resolved.checkpoint_path(44)


def _resolve_device(device_text: str | None = None) -> Any:
    return reverse_engine.resolve_device(device_text or ForwardModelSettings.from_env().device)


def run_reverse_design(
    *,
    inlet1: float,
    inlet2: float,
    target_concentrations: list[float],
    device: str | None = None,
    checkpoint_path: str | Path | None = None,
    parameters: ReverseOptimizationParameters | None = None,
) -> dict[str, Any]:
    params = parameters or ReverseOptimizationParameters()
    if len(target_concentrations) != reverse_engine.CHIP_COUNT:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_INPUT_SCHEMA_ERROR,
            "Reverse design requires exactly six target concentrations.",
        )

    target = np.asarray(target_concentrations, dtype=np.float32)
    warnings: list[str] = []
    if (
        float(target.min()) < params.target_recommended_min
        or float(target.max()) > params.target_recommended_max
    ):
        warnings.append(
            "目标浓度中包含超出推荐密集训练范围 [0.10, 0.95] 的数值，请谨慎评估结果。"
        )

    started = time.perf_counter()
    try:
        torch_device = _resolve_device(device)
        checkpoint = Path(checkpoint_path) if checkpoint_path is not None else _resolve_checkpoint()
        loaded = reverse_engine.load_forward_model(checkpoint_path=checkpoint, device=torch_device)
        reverse_engine.set_seed(params.seed)
        sample = reverse_engine.TargetSample(
            name="reverse-design",
            inlet1=float(inlet1),
            inlet2=float(inlet2),
            concentration=target,
        )
        result = reverse_engine.optimize_one_target(
            sample=sample,
            loaded=loaded,
            device=torch_device,
            width_min=reverse_engine.DEFAULT_WIDTH_MIN_MM,
            width_max=reverse_engine.DEFAULT_WIDTH_MAX_MM,
            steps=params.steps,
            refine_steps=params.refine_steps,
            learning_rate=params.learning_rate,
            restarts=params.restarts,
            seed=params.seed,
            temperature_start=params.temperature_start,
            temperature_end=params.temperature_end,
            lambda_mae=params.lambda_mae,
            lambda_width_center=params.lambda_width_center,
            lambda_bend_complexity=params.lambda_bend_complexity,
            lambda_entropy=params.lambda_entropy,
            min_mean_flow=params.min_mean_flow,
            screening_mae=params.screening_mae,
            screening_rmse=params.screening_rmse,
            screening_maxae=params.screening_maxae,
            screening_spearman=params.screening_spearman,
            log_every=params.log_every,
        )
    except ModelRuntimeError:
        raise
    except Exception as exc:
        raise ModelRuntimeError(
            ModelErrorCode.REVERSE_MODEL_UNAVAILABLE,
            "Reverse design failed to run.",
            {"error": type(exc).__name__},
        ) from exc

    chips: list[dict[str, Any]] = []
    for index in range(reverse_engine.CHIP_COUNT):
        left_bend = int(result.bends[index, 0])
        right_bend = int(result.bends[index, 1])
        target_value = float(result.target[index])
        predicted_value = float(result.predicted[index])
        chips.append(
            {
                "position": index + 1,
                "point_labels": [f"P{index * 2 + 1}", f"P{index * 2 + 2}"],
                "chip_type": f"{left_bend}to{right_bend}",
                "left_width_mm": round(float(result.widths[index, 0]), 6),
                "right_width_mm": round(float(result.widths[index, 1]), 6),
                "left_bend_class": left_bend,
                "right_bend_class": right_bend,
                "left_distance_mm": float(result.distances[index, 0]),
                "right_distance_mm": float(result.distances[index, 1]),
                "target_concentration": target_value,
                "predicted_concentration": predicted_value,
                "absolute_error": abs(predicted_value - target_value),
            }
        )

    return {
        "inlet1": float(inlet1),
        "inlet2": float(inlet2),
        "target_concentrations": [float(item) for item in target_concentrations],
        "chips": chips,
        "metrics": {
            "mae": float(result.mae),
            "rmse": float(result.rmse),
            "maxae": float(result.maxae),
            "spearman": float(result.spearman),
            "internal_screening_pass": bool(result.screening_pass),
            "selected_restart": int(result.restart_index),
        },
        "warnings": warnings,
        "notes": [
            "内部筛选仅表示该结构已通过同一 Physics-GNN 代理模型的检查。",
            "最终设计仍需使用 Fluent/CFD 进行独立验证。",
        ],
        "elapsed_seconds": time.perf_counter() - started,
    }
