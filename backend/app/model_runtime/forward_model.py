from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import TransformerConv, global_mean_pool

from app.core.config import ForwardModelSettings
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.model_runtime.graph_builder import safe_torch_load


class DataOnlyGNNTransformer(nn.Module):
    def __init__(
        self,
        *,
        in_channels: int,
        edge_dim: int,
        global_feature_dim: int,
        hidden_channels: int,
        output_dim: int,
        heads: int,
        num_layers: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if num_layers < 1:
            raise ValueError("num_layers must be at least 1")

        self.input_projection = nn.Linear(in_channels, hidden_channels)
        self.convs = nn.ModuleList(
            [
                TransformerConv(
                    in_channels=hidden_channels,
                    out_channels=hidden_channels,
                    heads=heads,
                    concat=False,
                    beta=True,
                    dropout=dropout,
                    edge_dim=edge_dim,
                    root_weight=True,
                )
                for _ in range(num_layers)
            ]
        )
        self.norms = nn.ModuleList([nn.LayerNorm(hidden_channels) for _ in range(num_layers)])
        self.dropout = nn.Dropout(dropout)

        fused_dim = hidden_channels + global_feature_dim
        self.regression_head = nn.Sequential(
            nn.Linear(fused_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, hidden_channels // 2),
            nn.LayerNorm(hidden_channels // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels // 2, output_dim),
        )

    def forward(self, data: Any) -> Tensor:
        x = F.gelu(self.input_projection(data.x))
        for conv, norm in zip(self.convs, self.norms):
            residual = x
            message = conv(x, data.edge_index, data.edge_attr)
            message = self.dropout(F.gelu(norm(message)))
            x = residual + message

        graph_embedding = global_mean_pool(x, data.batch)
        global_features = data.u.reshape(data.num_graphs, -1)
        fused = torch.cat([graph_embedding, global_features], dim=1)
        return self.regression_head(fused)


@dataclass
class LoadedForwardModel:
    seed: int
    model: nn.Module
    normalizers: dict[str, Tensor]
    checkpoint_path: Path


def select_device(configured: str) -> torch.device:
    if configured == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if configured == "cuda" and not torch.cuda.is_available():
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_CHECKPOINT_INVALID,
            "MODEL_DEVICE=cuda was requested but CUDA is not available.",
        )
    if configured not in {"cpu", "cuda"}:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_CHECKPOINT_INVALID,
            "MODEL_DEVICE must be one of auto, cpu, cuda.",
            {"device": configured},
        )
    return torch.device(configured)


def infer_output_dim(state_dict: Mapping[str, Tensor]) -> int:
    for key in ("regression_head.8.weight", "regression_head.8.bias"):
        tensor = state_dict.get(key)
        if torch.is_tensor(tensor):
            return int(tensor.shape[0])
    raise ModelRuntimeError(
        ModelErrorCode.MODEL_CHECKPOINT_INVALID,
        "Could not infer model output dimension from checkpoint.",
    )


class ForwardModelLoader:
    required_normalizers = ("x_mean", "x_std", "edge_mean", "edge_std", "u_mean", "u_std")

    def __init__(self, settings: ForwardModelSettings) -> None:
        self.settings = settings
        self.device = select_device(settings.device)

    def load_all(self) -> list[LoadedForwardModel]:
        models = [self._load_one(seed, self.settings.checkpoint_path(seed)) for seed in self.settings.seeds]
        return models

    def _load_one(self, seed: int, path: Path) -> LoadedForwardModel:
        if not path.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "Model checkpoint was not found.",
                {"seed": seed, "path": str(path)},
            )

        try:
            checkpoint = safe_torch_load(path)
            if not isinstance(checkpoint, Mapping):
                raise TypeError("checkpoint is not a mapping")
            checkpoint = dict(checkpoint)

            variant = str(checkpoint.get("ablation_variant") or "").strip()
            if variant and variant != "data_only":
                raise ValueError(f"ablation_variant must be data_only, got {variant}")

            state_dict = checkpoint.get("model_state_dict")
            normalizers = checkpoint.get("normalizers")
            architecture = dict(checkpoint.get("architecture", {}))
            if not isinstance(state_dict, Mapping):
                raise KeyError("model_state_dict")
            if not isinstance(normalizers, Mapping):
                raise KeyError("normalizers")
            missing = [name for name in self.required_normalizers if name not in normalizers]
            if missing:
                raise KeyError(f"missing normalizers: {missing}")

            output_dim = infer_output_dim(state_dict)
            model = DataOnlyGNNTransformer(
                in_channels=int(architecture.get("in_channels", normalizers["x_mean"].numel())),
                edge_dim=int(architecture.get("edge_dim", normalizers["edge_mean"].numel())),
                global_feature_dim=int(architecture.get("global_feature_dim", normalizers["u_mean"].numel())),
                hidden_channels=int(architecture.get("hidden_channels", 128)),
                output_dim=output_dim,
                heads=int(architecture.get("heads", 4)),
                num_layers=int(architecture.get("layers", architecture.get("num_layers", 3))),
                dropout=float(architecture.get("dropout", 0.10)),
            )
            model.load_state_dict(state_dict, strict=True)
            model.to(self.device)
            model.eval()

            return LoadedForwardModel(
                seed=seed,
                model=model,
                normalizers={name: normalizers[name] for name in self.required_normalizers},
                checkpoint_path=path,
            )
        except ModelRuntimeError:
            raise
        except Exception as exc:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_CHECKPOINT_INVALID,
                "Failed to load model checkpoint.",
                {"seed": seed, "path": str(path), "error": str(exc)},
            ) from exc
