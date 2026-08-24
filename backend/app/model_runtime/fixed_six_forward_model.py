from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import TransformerConv

from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.model_runtime.graph_builder import (
    CHIP_NODE_START_INDEX,
    EXPECTED_CHIP_PHYSICS_DIM,
    EXPECTED_EDGE_FEATURE_DIM,
    EXPECTED_GLOBAL_FEATURE_DIM,
    EXPECTED_NODE_FEATURE_DIM,
    INLET1_NODE_INDEX,
    INLET2_NODE_INDEX,
    NODE_TYPE_CHIP,
    NODE_TYPE_INLET1,
    NODE_TYPE_INLET2,
    InputChip,
    InputSample,
    RawGraph,
    build_inlet_node_row,
    build_raw_chip_physics,
    build_raw_u,
    normalize_tensor,
    parse_chip_structure,
)
from app.model_runtime.forward_model import FLOW_EPS, LoadedForwardModel
from app.schemas.forward import ForwardPredictionRequest


EXPECTED_CHIP_COUNT = 6
EXPECTED_NODE_COUNT = 8
EXPECTED_EDGE_COUNT = 24
EXPECTED_OUTPUT_DIM = 6


class FixedSixPhysicsGuidedDualTaskGNN(nn.Module):
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
            raise RuntimeError("Each fixed-six graph must contain exactly 8 nodes.")

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


@dataclass(frozen=True)
class FixedSixRuntimeModel:
    seed: int
    model: nn.Module
    normalizers: dict[str, Tensor]


def clone_fixed_six_model(model_info: LoadedForwardModel, device: torch.device) -> FixedSixRuntimeModel:
    source = model_info.model
    model = FixedSixPhysicsGuidedDualTaskGNN(
        in_channels=int(source.in_channels),
        edge_dim=int(source.edge_dim),
        global_feature_dim=int(source.global_feature_dim),
        hidden_channels=int(source.hidden_channels),
        heads=int(source.heads),
        num_layers=int(source.num_layers),
        dropout=float(source.dropout_rate),
        use_edge_attr=bool(source.use_edge_attr),
        x_mean=model_info.normalizers["x_mean"],
        x_std=model_info.normalizers["x_std"],
        u_mean=model_info.normalizers["u_mean"],
        u_std=model_info.normalizers["u_std"],
        flow_log_mean=model_info.normalizers["flow_log_mean"],
        flow_log_std=model_info.normalizers["flow_log_std"],
    )
    model.load_state_dict(source.state_dict(), strict=True)
    model.to(device)
    model.eval()
    return FixedSixRuntimeModel(seed=model_info.seed, model=model, normalizers=model_info.normalizers)


def build_fixed_six_chip_node_row(chip: InputChip, chip_index: int) -> list[float]:
    chip_start_norm, chip_end_norm, chip_signed_span_norm, chip_absolute_span_norm = parse_chip_structure(
        chip.chip_name
    )
    assembly_position = float(chip_index) / float(EXPECTED_CHIP_COUNT - 1)
    row = [
        0.0,
        0.0,
        1.0,
        0.0,
        float(chip.left_width_mm),
        float(chip.right_width_mm),
        float(chip.left_distance_mm),
        float(chip.right_distance_mm),
        float(chip.left_position),
        float(chip.right_position),
        assembly_position,
        chip_start_norm,
        chip_end_norm,
        chip_signed_span_norm,
        chip_absolute_span_norm,
    ]
    if len(row) != EXPECTED_NODE_FEATURE_DIM:
        raise RuntimeError("chip node feature dimension must be 15")
    return row


def build_fixed_six_raw_x(sample: InputSample) -> Tensor:
    rows = [build_inlet_node_row(1, sample.inlet1), build_inlet_node_row(2, sample.inlet2)]
    rows.extend(build_fixed_six_chip_node_row(chip, chip_index) for chip_index, chip in enumerate(sample.chips))
    x = torch.tensor(rows, dtype=torch.float32)
    if tuple(x.shape) != (EXPECTED_NODE_COUNT, EXPECTED_NODE_FEATURE_DIM):
        raise RuntimeError(f"x shape must be (8, 15), got {tuple(x.shape)}")
    return x


def build_fixed_six_raw_edges(sample: InputSample) -> tuple[Tensor, Tensor]:
    sources: list[int] = []
    targets: list[int] = []
    features: list[list[float]] = []

    def append_edge(
        source: int,
        target: int,
        width: float,
        distance: float,
        assembly_position: float,
        chip_signed_span_norm: float,
        chip_absolute_span_norm: float,
        side_is_inlet1: float,
        side_is_inlet2: float,
        direction_to_chip: float,
        direction_from_chip: float,
    ) -> None:
        sources.append(source)
        targets.append(target)
        features.append(
            [
                float(width),
                float(distance),
                float(assembly_position),
                float(chip_signed_span_norm),
                float(chip_absolute_span_norm),
                float(side_is_inlet1),
                float(side_is_inlet2),
                float(direction_to_chip),
                float(direction_from_chip),
            ]
        )

    for chip_index, chip in enumerate(sample.chips):
        chip_node_index = CHIP_NODE_START_INDEX + chip_index
        assembly_position = float(chip_index) / float(EXPECTED_CHIP_COUNT - 1)
        _, _, chip_signed_span_norm, chip_absolute_span_norm = parse_chip_structure(chip.chip_name)
        append_edge(INLET1_NODE_INDEX, chip_node_index, chip.left_width_mm, chip.left_distance_mm, assembly_position, chip_signed_span_norm, chip_absolute_span_norm, 1.0, 0.0, 1.0, 0.0)
        append_edge(INLET2_NODE_INDEX, chip_node_index, chip.right_width_mm, chip.right_distance_mm, assembly_position, chip_signed_span_norm, chip_absolute_span_norm, 0.0, 1.0, 1.0, 0.0)
        append_edge(chip_node_index, INLET1_NODE_INDEX, chip.left_width_mm, chip.left_distance_mm, assembly_position, chip_signed_span_norm, chip_absolute_span_norm, 1.0, 0.0, 0.0, 1.0)
        append_edge(chip_node_index, INLET2_NODE_INDEX, chip.right_width_mm, chip.right_distance_mm, assembly_position, chip_signed_span_norm, chip_absolute_span_norm, 0.0, 1.0, 0.0, 1.0)

    edge_index = torch.tensor([sources, targets], dtype=torch.long)
    edge_attr = torch.tensor(features, dtype=torch.float32)
    if tuple(edge_index.shape) != (2, EXPECTED_EDGE_COUNT):
        raise RuntimeError(f"edge_index shape must be (2, 24), got {tuple(edge_index.shape)}")
    if tuple(edge_attr.shape) != (EXPECTED_EDGE_COUNT, EXPECTED_EDGE_FEATURE_DIM):
        raise RuntimeError(f"edge_attr shape must be (24, 9), got {tuple(edge_attr.shape)}")
    return edge_index, edge_attr


class FixedSixGraphBuilder:
    def __init__(self, normalizers: dict[str, Tensor]) -> None:
        self.normalizers = normalizers

    def _sample_from_request(self, request: ForwardPredictionRequest) -> InputSample:
        if request.chip_count != EXPECTED_CHIP_COUNT:
            raise ValueError("fixed-six runtime only accepts chip_count=6")
        chips = tuple(
            InputChip(
                chip_name=chip.chip_type,
                left_width_mm=float(chip.left_width_mm),
                right_width_mm=float(chip.right_width_mm),
                left_distance_mm=float(chip.left_bend_straight_distance_mm),
                right_distance_mm=float(chip.right_bend_straight_distance_mm),
                left_position=float(chip.position),
                right_position=float(chip.position),
            )
            for chip in request.chips_by_position()
        )
        if len(chips) != EXPECTED_CHIP_COUNT:
            raise ValueError("fixed-six runtime requires exactly 6 chips")
        return InputSample(
            sample_name=request.sample_name,
            inlet1=float(request.inlet1),
            inlet2=float(request.inlet2),
            chips=chips,
        )

    def build_raw_graph(self, request: ForwardPredictionRequest) -> RawGraph:
        try:
            sample = self._sample_from_request(request)
            raw_x = build_fixed_six_raw_x(sample)
            raw_edge_index, raw_edge_attr = build_fixed_six_raw_edges(sample)
            raw_u = build_raw_u(sample)
            raw_chip_physics = build_raw_chip_physics(sample)
            normalized_x = normalize_tensor(raw_x, self.normalizers["x_mean"], self.normalizers["x_std"], "x")
            normalized_edge_attr = normalize_tensor(
                raw_edge_attr,
                self.normalizers["edge_mean"],
                self.normalizers["edge_std"],
                "edge_attr",
            )
            normalized_u = normalize_tensor(raw_u, self.normalizers["u_mean"], self.normalizers["u_std"], "u")
            chip_physics_z = normalize_tensor(
                raw_chip_physics,
                self.normalizers["chip_physics_mean"],
                self.normalizers["chip_physics_std"],
                "chip_physics",
            )
            return RawGraph(
                x=normalized_x,
                edge_index=raw_edge_index,
                edge_attr=normalized_edge_attr,
                u=normalized_u,
                chip_physics=raw_chip_physics,
                chip_physics_z=chip_physics_z,
                node_type=torch.tensor(
                    [NODE_TYPE_INLET1, NODE_TYPE_INLET2] + [NODE_TYPE_CHIP] * EXPECTED_CHIP_COUNT,
                    dtype=torch.long,
                ),
            )
        except Exception as exc:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_INPUT_SCHEMA_ERROR,
                "Failed to build fixed-six Physics-GNN graph.",
                {"error": str(exc)},
            ) from exc
