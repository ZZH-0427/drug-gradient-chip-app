from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import TransformerConv

from app.core.config import ForwardModelSettings
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.model_runtime.graph_builder import (
    EXPECTED_CHIP_COUNT,
    EXPECTED_CHIP_PHYSICS_DIM,
    EXPECTED_EDGE_FEATURE_DIM,
    EXPECTED_GLOBAL_FEATURE_DIM,
    EXPECTED_NODE_COUNT,
    EXPECTED_NODE_FEATURE_DIM,
    CHIP_NODE_START_INDEX,
    safe_torch_load,
)


FLOW_EPS = 1.0e-18


class PhysicsGuidedDualTaskGNN(nn.Module):
    def __init__(
        self,
        *,
        in_channels: int,
        edge_dim: int,
        global_feature_dim: int,
        hidden_channels: int,
        heads: int,
        num_layers: int,
        dropout: float,
        use_edge_attr: bool,
        x_mean: Tensor,
        x_std: Tensor,
        u_mean: Tensor,
        u_std: Tensor,
        flow_log_mean: Tensor,
        flow_log_std: Tensor,
    ) -> None:
        super().__init__()
        if num_layers < 1:
            raise ValueError("num_layers must be at least 1")

        self.in_channels = int(in_channels)
        self.edge_dim = int(edge_dim)
        self.global_feature_dim = int(global_feature_dim)
        self.hidden_channels = int(hidden_channels)
        self.heads = int(heads)
        self.num_layers = int(num_layers)
        self.dropout_rate = float(dropout)
        self.use_edge_attr = bool(use_edge_attr)

        self.register_buffer("x_mean", x_mean.detach().float().reshape(1, -1))
        self.register_buffer("x_std", x_std.detach().float().reshape(1, -1))
        self.register_buffer("u_mean", u_mean.detach().float().reshape(1, -1))
        self.register_buffer("u_std", u_std.detach().float().reshape(1, -1))
        self.register_buffer("flow_log_mean", flow_log_mean.detach().float().reshape(1))
        self.register_buffer("flow_log_std", flow_log_std.detach().float().reshape(1))

        self.input_projection = nn.Linear(in_channels + EXPECTED_CHIP_PHYSICS_DIM, hidden_channels)
        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()
        for _ in range(num_layers):
            kwargs: dict[str, Any] = {
                "in_channels": hidden_channels,
                "out_channels": hidden_channels,
                "heads": heads,
                "concat": False,
                "beta": True,
                "dropout": dropout,
                "root_weight": True,
            }
            if self.use_edge_attr:
                kwargs["edge_dim"] = edge_dim
            self.convs.append(TransformerConv(**kwargs))
            self.norms.append(nn.LayerNorm(hidden_channels))
        self.dropout = nn.Dropout(dropout)

        self.raw_width_ratio_weight = nn.Parameter(torch.tensor(-0.2))
        self.raw_distance_ratio_weight = nn.Parameter(torch.tensor(-0.2))
        self.local_concentration_bias = nn.Parameter(torch.zeros(1))
        self.concentration_global_gate = nn.Parameter(torch.tensor(-2.0))

        context_dim = hidden_channels + hidden_channels + EXPECTED_CHIP_PHYSICS_DIM + global_feature_dim
        self.concentration_correction_head = nn.Sequential(
            nn.Linear(context_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, hidden_channels // 2),
            nn.GELU(),
            nn.Linear(hidden_channels // 2, 1),
        )
        self.flow_head = nn.Sequential(
            nn.Linear(context_dim, hidden_channels),
            nn.LayerNorm(hidden_channels),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_channels, hidden_channels // 2),
            nn.GELU(),
            nn.Linear(hidden_channels // 2, 1),
        )

    def recover_raw_u(self, normalized_u: Tensor) -> Tensor:
        return normalized_u * self.u_std + self.u_mean

    def decode_flow(self, flow_log_z: Tensor) -> Tensor:
        flow_log = flow_log_z * self.flow_log_std + self.flow_log_mean
        return torch.exp(flow_log).clamp_min(FLOW_EPS)

    def forward(self, data: Any) -> dict[str, Tensor]:
        graph_count = int(data.num_graphs)
        if int(data.x.shape[0]) != graph_count * EXPECTED_NODE_COUNT:
            raise RuntimeError("Each graph must contain exactly 8 nodes.")

        node_x = data.x.reshape(graph_count, EXPECTED_NODE_COUNT, self.in_channels)
        chip_physics_z = data.chip_physics_z.reshape(
            graph_count,
            EXPECTED_CHIP_COUNT,
            EXPECTED_CHIP_PHYSICS_DIM,
        )
        chip_physics_raw = data.chip_physics.reshape(
            graph_count,
            EXPECTED_CHIP_COUNT,
            EXPECTED_CHIP_PHYSICS_DIM,
        )

        physics_for_nodes = torch.zeros(
            (graph_count, EXPECTED_NODE_COUNT, EXPECTED_CHIP_PHYSICS_DIM),
            dtype=node_x.dtype,
            device=node_x.device,
        )
        physics_for_nodes[:, CHIP_NODE_START_INDEX:, :] = chip_physics_z
        node_input = torch.cat([node_x, physics_for_nodes], dim=2).reshape(
            graph_count * EXPECTED_NODE_COUNT,
            -1,
        )

        hidden = F.gelu(self.input_projection(node_input))
        for conv, norm in zip(self.convs, self.norms):
            residual = hidden
            message = conv(hidden, data.edge_index, data.edge_attr) if self.use_edge_attr else conv(hidden, data.edge_index)
            message = self.dropout(F.gelu(norm(message)))
            hidden = residual + message

        node_hidden = hidden.reshape(graph_count, EXPECTED_NODE_COUNT, self.hidden_channels)
        chip_hidden = node_hidden[:, CHIP_NODE_START_INDEX:, :]
        graph_context = node_hidden.mean(dim=1, keepdim=True).expand(-1, EXPECTED_CHIP_COUNT, -1)
        raw_u = self.recover_raw_u(data.u.reshape(graph_count, -1))
        u_context = raw_u.unsqueeze(1).expand(-1, EXPECTED_CHIP_COUNT, -1)
        context = torch.cat([chip_hidden, graph_context, chip_physics_z, u_context], dim=2)

        width_weight = F.softplus(self.raw_width_ratio_weight)
        distance_weight = F.softplus(self.raw_distance_ratio_weight)
        local_logit = (
            self.local_concentration_bias
            + width_weight * chip_physics_raw[:, :, 0]
            + distance_weight * chip_physics_raw[:, :, 4]
        )
        correction = self.concentration_correction_head(context).squeeze(-1)
        gate = torch.sigmoid(self.concentration_global_gate)
        alpha = torch.sigmoid(local_logit + gate * correction)
        inlet1 = raw_u[:, 0:1]
        inlet2 = raw_u[:, 1:2]
        concentration = inlet2 + alpha * (inlet1 - inlet2)

        flow_log_z = self.flow_head(context).squeeze(-1)
        flow = self.decode_flow(flow_log_z)
        return {
            "concentration": concentration,
            "flow_log_z": flow_log_z,
            "flow": flow,
            "mixing_fraction": alpha,
            "raw_u": raw_u,
        }


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
            "FORWARD_MODEL_DEVICE=cuda was requested but CUDA is not available.",
        )
    if configured not in {"cpu", "cuda"}:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_CHECKPOINT_INVALID,
            "FORWARD_MODEL_DEVICE must be one of auto, cpu, cuda.",
            {"device": configured},
        )
    return torch.device(configured)


class ForwardModelLoader:
    required_normalizers = (
        "x_mean",
        "x_std",
        "edge_mean",
        "edge_std",
        "u_mean",
        "u_std",
        "chip_physics_mean",
        "chip_physics_std",
        "flow_log_mean",
        "flow_log_std",
    )

    def __init__(self, settings: ForwardModelSettings) -> None:
        self.settings = settings
        self.device = select_device(settings.device)

    def load_all(self) -> list[LoadedForwardModel]:
        return [self._load_one(44, self.settings.checkpoint_path(44))]

    def _load_one(self, seed: int, path: Path) -> LoadedForwardModel:
        if not path.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "Model checkpoint was not found.",
                {"path": str(path)},
            )
        try:
            checkpoint = safe_torch_load(path)
            if not isinstance(checkpoint, Mapping):
                raise TypeError("checkpoint is not a mapping")
            checkpoint = dict(checkpoint)
            architecture = dict(checkpoint.get("architecture", {}))
            if architecture.get("model_type") != "PhysicsGuidedDualTaskGNN":
                raise ValueError("checkpoint model_type is not PhysicsGuidedDualTaskGNN")
            state_dict = checkpoint.get("model_state_dict")
            normalizers_raw = checkpoint.get("normalizers")
            if not isinstance(state_dict, Mapping):
                raise KeyError("model_state_dict")
            if not isinstance(normalizers_raw, Mapping):
                raise KeyError("normalizers")
            missing = [name for name in self.required_normalizers if name not in normalizers_raw]
            if missing:
                raise KeyError(f"missing normalizers: {missing}")
            normalizers = {name: normalizers_raw[name] for name in self.required_normalizers}

            in_channels = int(architecture.get("in_channels", normalizers["x_mean"].numel()))
            edge_dim = int(architecture.get("edge_dim", normalizers["edge_mean"].numel()))
            global_feature_dim = int(architecture.get("global_feature_dim", normalizers["u_mean"].numel()))
            chip_dim = int(architecture.get("chip_physics_feature_dim", EXPECTED_CHIP_PHYSICS_DIM))
            if in_channels != EXPECTED_NODE_FEATURE_DIM or edge_dim != EXPECTED_EDGE_FEATURE_DIM:
                raise ValueError("checkpoint feature dimensions do not match formal Physics-GNN")
            if global_feature_dim != EXPECTED_GLOBAL_FEATURE_DIM or chip_dim != EXPECTED_CHIP_PHYSICS_DIM:
                raise ValueError("checkpoint context dimensions do not match formal Physics-GNN")

            model = PhysicsGuidedDualTaskGNN(
                in_channels=in_channels,
                edge_dim=edge_dim,
                global_feature_dim=global_feature_dim,
                hidden_channels=int(architecture.get("hidden_channels", 128)),
                heads=int(architecture.get("heads", 4)),
                num_layers=int(architecture.get("layers", architecture.get("num_layers", 3))),
                dropout=float(architecture.get("dropout", 0.1)),
                use_edge_attr=bool(architecture.get("use_edge_attr", True)),
                x_mean=normalizers["x_mean"],
                x_std=normalizers["x_std"],
                u_mean=normalizers["u_mean"],
                u_std=normalizers["u_std"],
                flow_log_mean=normalizers["flow_log_mean"],
                flow_log_std=normalizers["flow_log_std"],
            )
            model.load_state_dict(dict(state_dict), strict=True)
            model.to(self.device)
            model.eval()
            return LoadedForwardModel(seed=seed, model=model, normalizers=normalizers, checkpoint_path=path)
        except ModelRuntimeError:
            raise
        except Exception as exc:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_CHECKPOINT_INVALID,
                "Failed to load model checkpoint.",
                {"path": str(path), "error": str(exc)},
            ) from exc
