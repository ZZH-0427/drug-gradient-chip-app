from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import ModelErrorCode, ModelRuntimeError


logger = logging.getLogger(__name__)
DEFAULT_SEEDS: tuple[int, ...] = (42, 52, 62, 72, 82)
CHECKPOINT_NAME = "best_ablation_checkpoint.pt"
VALID_DEVICES = {"auto", "cpu", "cuda"}
DEFAULT_FRONTEND_ORIGINS: tuple[str, ...] = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ForwardModelSettings:
    asset_root: Path
    asset_source: str
    model_source_root: Path | None = None
    device: str = "cpu"
    seeds: tuple[int, ...] = DEFAULT_SEEDS
    checkpoint_name: str = CHECKPOINT_NAME

    @classmethod
    def from_env(cls) -> "ForwardModelSettings":
        device = resolve_forward_model_device()
        raw_root = os.getenv("MODEL_SOURCE_ROOT", "")

        if raw_root.strip():
            source_root = Path(raw_root.strip())
            return cls(
                asset_root=source_root,
                asset_source="external",
                model_source_root=source_root,
                device=device,
            )

        return cls(
            asset_root=project_root() / "model_assets" / "forward",
            asset_source="bundled",
            model_source_root=None,
            device=device,
        )

    @property
    def manifest_path(self) -> Path:
        return self.asset_root / "manifest.json"

    @property
    def checkpoint_root(self) -> Path:
        if self.asset_source == "external":
            return (
                self.asset_root
                / "GNN"
                / "Physics-GNN"
                / "model"
                / "ablation"
                / "data_only"
            )
        return self.asset_root / "checkpoints"

    @property
    def dataset_path(self) -> Path:
        if self.asset_source == "external":
            return self.asset_root / "GNN" / "Gnndata" / "physics_gnn_dataset.pt"
        return self.asset_root / "graph_template" / "physics_gnn_dataset.pt"

    @property
    def dataset_summary_path(self) -> Path:
        if self.asset_source == "external":
            return self.asset_root / "GNN" / "Gnndata" / "physics_gnn_dataset_summary.json"
        return self.asset_root / "graph_template" / "physics_gnn_dataset_summary.json"

    def checkpoint_path(self, seed: int) -> Path:
        return self.checkpoint_root / f"seed_{seed}" / self.checkpoint_name

    def validate_assets(self) -> None:
        if self.asset_source not in {"bundled", "external"}:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_CONFIGURATION_ERROR,
                "Forward model asset source is invalid.",
            )

        if self.asset_source == "external" and not self.asset_root.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_CONFIGURATION_ERROR,
                "Configured external model source root does not exist.",
                {"path": str(self.asset_root)},
            )

        if self.asset_source == "bundled" and not self.asset_root.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "Bundled forward model assets are not provisioned.",
                {"path": str(self.asset_root)},
            )

        required = [self.dataset_path, *[self.checkpoint_path(seed) for seed in self.seeds]]
        missing = [path for path in required if not path.exists()]
        empty = [path for path in required if path.exists() and path.stat().st_size <= 0]

        if missing or empty:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "Forward model assets are missing or empty.",
                {
                    "missing": [str(path) for path in missing],
                    "empty": [str(path) for path in empty],
                },
            )

        if len(self.seeds) != 5 or tuple(self.seeds) != DEFAULT_SEEDS:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_CONFIGURATION_ERROR,
                "Forward model seeds must be exactly 42,52,62,72,82.",
            )

        if self.asset_source == "bundled" and not self.manifest_path.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "Bundled forward model manifest is missing.",
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


def resolve_frontend_origins() -> list[str]:
    raw_origins = os.getenv("FRONTEND_ORIGINS")
    if raw_origins is None:
        return list(DEFAULT_FRONTEND_ORIGINS)

    origins: list[str] = []
    seen: set[str] = set()
    for item in raw_origins.split(","):
        origin = item.strip()
        if not origin or origin in seen:
            continue
        origins.append(origin)
        seen.add(origin)
    return origins
