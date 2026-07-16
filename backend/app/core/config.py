from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ModelErrorCode, ModelRuntimeError


logger = logging.getLogger(__name__)
DEFAULT_SEEDS: tuple[int, ...] = (42, 52, 62, 72, 82)
CHECKPOINT_NAME = "best_ablation_checkpoint.pt"
VALID_DEVICES = {"auto", "cpu", "cuda"}


@dataclass(frozen=True)
class ForwardModelSettings:
    model_source_root: Path
    device: str = "auto"
    seeds: tuple[int, ...] = DEFAULT_SEEDS
    checkpoint_name: str = CHECKPOINT_NAME

    @classmethod
    def from_env(cls) -> "ForwardModelSettings":
        raw_root = os.getenv("MODEL_SOURCE_ROOT", "").strip()
        if not raw_root:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_SOURCE_ROOT_MISSING,
                "MODEL_SOURCE_ROOT is not configured.",
            )
        device = resolve_forward_model_device()
        return cls(
            model_source_root=Path(raw_root),
            device=device,
        )

    @property
    def forward_script_path(self) -> Path:
        return (
            self.model_source_root
            / "正向预测与反向预测"
            / "正向预测"
            / "forward_predict.py"
        )

    @property
    def checkpoint_root(self) -> Path:
        return (
            self.model_source_root
            / "GNN"
            / "Physics-GNN"
            / "model"
            / "ablation"
            / "data_only"
        )

    @property
    def dataset_path(self) -> Path:
        return self.model_source_root / "GNN" / "Gnndata" / "physics_gnn_dataset.pt"

    @property
    def dataset_summary_path(self) -> Path:
        return (
            self.model_source_root
            / "GNN"
            / "Gnndata"
            / "physics_gnn_dataset_summary.json"
        )

    @property
    def golden_input_path(self) -> Path:
        return (
            self.model_source_root
            / "正向预测与反向预测"
            / "正向预测"
            / "正向预测输入"
            / "正向预测.csv"
        )

    @property
    def golden_output_path(self) -> Path:
        return (
            self.model_source_root
            / "正向预测与反向预测"
            / "正向预测"
            / "正向预测结果"
            / "forward_prediction_results.csv"
        )

    def checkpoint_path(self, seed: int) -> Path:
        return self.checkpoint_root / f"seed_{seed}" / self.checkpoint_name

    def validate_assets(self) -> None:
        if not self.model_source_root.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_SOURCE_ROOT_MISSING,
                "MODEL_SOURCE_ROOT does not exist.",
                {"path": str(self.model_source_root)},
            )

        required = [
            self.dataset_path,
            self.golden_input_path,
            self.golden_output_path,
            self.forward_script_path,
            *[self.checkpoint_path(seed) for seed in self.seeds],
        ]
        missing = [path for path in required if not path.exists()]
        if missing:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "One or more model assets were not found.",
                {"missing": [str(path) for path in missing]},
            )


def resolve_forward_model_device() -> str:
    new_value = os.getenv("FORWARD_MODEL_DEVICE")
    old_value = os.getenv("MODEL_DEVICE")

    if new_value is not None:
        device = new_value.strip() or "cpu"
        if old_value is not None and old_value.strip() and old_value.strip() != device:
            logger.warning(
                "Both FORWARD_MODEL_DEVICE and MODEL_DEVICE are set; using FORWARD_MODEL_DEVICE."
            )
    elif old_value is not None:
        device = old_value.strip() or "cpu"
    else:
        device = "cpu"

    if device not in VALID_DEVICES:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_CONFIGURATION_ERROR,
            "FORWARD_MODEL_DEVICE must be one of auto, cpu, cuda.",
            {"device": device},
        )
    return device
