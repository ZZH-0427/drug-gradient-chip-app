from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import Tensor

from app.core.config import ForwardModelSettings
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.schemas.forward import ForwardPredictionRequest


TRAIN_CHIP_COUNT = 6
TRAIN_NODE_COUNT = 8
TRAIN_EDGE_COUNT = 24
EXPECTED_NODE_FEATURE_DIM = 15
EXPECTED_EDGE_FEATURE_DIM = 9
EXPECTED_GLOBAL_FEATURE_DIM = 2
EXPECTED_CHIP_PHYSICS_DIM = 7
INLET1_NODE_INDEX = 0
INLET2_NODE_INDEX = 1
CHIP_NODE_START_INDEX = 2
NODE_TYPE_INLET1 = 0
NODE_TYPE_INLET2 = 1
NODE_TYPE_CHIP = 2
CHANNEL_PATTERN = re.compile(r"(\d+)\s*to\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class RawGraph:
    x: Tensor
    edge_index: Tensor
    edge_attr: Tensor
    u: Tensor
    chip_physics: Tensor
    chip_physics_z: Tensor
    node_type: Tensor


@dataclass(frozen=True)
class InputChip:
    chip_name: str
    left_width_mm: float
    right_width_mm: float
    left_distance_mm: float
    right_distance_mm: float
    left_position: float
    right_position: float


@dataclass(frozen=True)
class InputSample:
    sample_name: str
    inlet1: float
    inlet2: float
    chips: tuple[InputChip, ...]

    @property
    def num_chips(self) -> int:
        return len(self.chips)


def safe_torch_load(path: Path) -> Any:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def normalize_tensor(value: Tensor, mean: Tensor, std: Tensor, display_name: str) -> Tensor:
    mean = mean.detach().cpu().float().reshape(1, -1)
    std = std.detach().cpu().float().reshape(1, -1)
    if value.shape[-1] != mean.numel():
        raise ValueError(f"{display_name} dimension mismatch: {value.shape[-1]} vs {mean.numel()}")
    safe_std = torch.where(std.abs() < 1.0e-12, torch.ones_like(std), std)
    return (value.float() - mean) / safe_std


def parse_chip_structure(chip_name: str) -> tuple[float, float, float, float]:
    match = CHANNEL_PATTERN.search(chip_name)
    if match is None:
        raise ValueError(f"Invalid chip_type: {chip_name}")
    start = float(match.group(1))
    end = float(match.group(2))
    if not (1.0 <= start <= 6.0 and 1.0 <= end <= 6.0):
        raise ValueError(f"chip_type endpoints must be 1..6: {chip_name}")
    signed_span = end - start
    return start / 6.0, end / 6.0, signed_span / 5.0, abs(signed_span) / 5.0


def encode_position_for_six_chip_checkpoint(position: float, num_chips: int) -> float:
    if num_chips < 2:
        raise ValueError("num_chips must be at least 2")
    relative = (float(position) - 1.0) / float(num_chips - 1)
    return 1.0 + 5.0 * relative


def assembly_position_norm(chip_index: int, num_chips: int) -> float:
    if num_chips < 2:
        raise ValueError("num_chips must be at least 2")
    return float(chip_index) / float(num_chips - 1)


def build_inlet_node_row(inlet_index: int, concentration: float) -> list[float]:
    if inlet_index == 1:
        node_type = [1.0, 0.0, 0.0]
    elif inlet_index == 2:
        node_type = [0.0, 1.0, 0.0]
    else:
        raise ValueError("inlet_index must be 1 or 2")
    row = node_type + [float(concentration), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    if len(row) != EXPECTED_NODE_FEATURE_DIM:
        raise RuntimeError("inlet node feature dimension must be 15")
    return row


def build_chip_node_row(chip: InputChip, chip_index: int, num_chips: int) -> list[float]:
    chip_start_norm, chip_end_norm, chip_signed_span_norm, chip_absolute_span_norm = parse_chip_structure(
        chip.chip_name
    )
    position_norm = assembly_position_norm(chip_index, num_chips)
    left_position_encoded = encode_position_for_six_chip_checkpoint(chip.left_position, num_chips)
    right_position_encoded = encode_position_for_six_chip_checkpoint(chip.right_position, num_chips)
    row = [
        0.0,
        0.0,
        1.0,
        0.0,
        float(chip.left_width_mm),
        float(chip.right_width_mm),
        float(chip.left_distance_mm),
        float(chip.right_distance_mm),
        float(left_position_encoded),
        float(right_position_encoded),
        position_norm,
        chip_start_norm,
        chip_end_norm,
        chip_signed_span_norm,
        chip_absolute_span_norm,
    ]
    if len(row) != EXPECTED_NODE_FEATURE_DIM:
        raise RuntimeError("chip node feature dimension must be 15")
    return row


def build_raw_x(sample: InputSample) -> Tensor:
    rows = [
        build_inlet_node_row(1, sample.inlet1),
        build_inlet_node_row(2, sample.inlet2),
    ]
    rows.extend(build_chip_node_row(chip, chip_index, sample.num_chips) for chip_index, chip in enumerate(sample.chips))
    x = torch.tensor(rows, dtype=torch.float32)
    expected_shape = (sample.num_chips + 2, EXPECTED_NODE_FEATURE_DIM)
    if tuple(x.shape) != expected_shape:
        raise RuntimeError(f"x shape must be {expected_shape}, got {tuple(x.shape)}")
    return x


def build_node_type(sample: InputSample) -> Tensor:
    return torch.tensor(
        [NODE_TYPE_INLET1, NODE_TYPE_INLET2] + [NODE_TYPE_CHIP] * sample.num_chips,
        dtype=torch.long,
    )


def build_raw_edges(sample: InputSample) -> tuple[Tensor, Tensor]:
    sources: list[int] = []
    targets: list[int] = []
    features: list[list[float]] = []

    def append_edge(
        source: int,
        target: int,
        width: float,
        distance: float,
        assembly_position_norm: float,
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
                float(assembly_position_norm),
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
        position_norm = assembly_position_norm(chip_index, sample.num_chips)
        _, _, signed_span_norm, absolute_span_norm = parse_chip_structure(chip.chip_name)
        append_edge(INLET1_NODE_INDEX, chip_node_index, chip.left_width_mm, chip.left_distance_mm, position_norm, signed_span_norm, absolute_span_norm, 1.0, 0.0, 1.0, 0.0)
        append_edge(INLET2_NODE_INDEX, chip_node_index, chip.right_width_mm, chip.right_distance_mm, position_norm, signed_span_norm, absolute_span_norm, 0.0, 1.0, 1.0, 0.0)
        append_edge(chip_node_index, INLET1_NODE_INDEX, chip.left_width_mm, chip.left_distance_mm, position_norm, signed_span_norm, absolute_span_norm, 1.0, 0.0, 0.0, 1.0)
        append_edge(chip_node_index, INLET2_NODE_INDEX, chip.right_width_mm, chip.right_distance_mm, position_norm, signed_span_norm, absolute_span_norm, 0.0, 1.0, 0.0, 1.0)

    edge_index = torch.tensor([sources, targets], dtype=torch.long)
    edge_attr = torch.tensor(features, dtype=torch.float32)
    expected_edge_count = 4 * sample.num_chips
    if tuple(edge_index.shape) != (2, expected_edge_count):
        raise RuntimeError(f"edge_index shape must be (2, {expected_edge_count}), got {tuple(edge_index.shape)}")
    if tuple(edge_attr.shape) != (expected_edge_count, EXPECTED_EDGE_FEATURE_DIM):
        raise RuntimeError(f"edge_attr shape must be ({expected_edge_count}, 9), got {tuple(edge_attr.shape)}")
    return edge_index, edge_attr


def build_raw_u(sample: InputSample) -> Tensor:
    u = torch.tensor([[sample.inlet1, sample.inlet2]], dtype=torch.float32)
    if tuple(u.shape) != (1, EXPECTED_GLOBAL_FEATURE_DIM):
        raise RuntimeError("u shape must be (1, 2)")
    return u


def build_raw_chip_physics(sample: InputSample) -> Tensor:
    rows: list[list[float]] = []
    eps = 1.0e-12
    for chip_index, chip in enumerate(sample.chips, start=1):
        left_width = float(chip.left_width_mm)
        right_width = float(chip.right_width_mm)
        left_distance = float(chip.left_distance_mm)
        right_distance = float(chip.right_distance_mm)
        if min(left_width, right_width, left_distance, right_distance) <= 0.0:
            raise ValueError(f"chip{chip_index} has non-positive width or distance")
        width_sum = left_width + right_width
        distance_sum = left_distance + right_distance
        rows.append(
            [
                math.log((left_width + eps) / (right_width + eps)),
                (left_width - right_width) / (width_sum + eps),
                math.sqrt(left_width * right_width),
                width_sum,
                math.log((right_distance + eps) / (left_distance + eps)),
                (right_distance - left_distance) / (distance_sum + eps),
                math.sqrt(left_distance * right_distance),
            ]
        )
    result = torch.tensor(rows, dtype=torch.float32)
    expected_shape = (sample.num_chips, EXPECTED_CHIP_PHYSICS_DIM)
    if tuple(result.shape) != expected_shape:
        raise RuntimeError(f"chip_physics shape must be {expected_shape}, got {tuple(result.shape)}")
    return result


class GraphBuilder:
    def __init__(self, settings: ForwardModelSettings, normalizers: dict[str, Tensor] | None = None) -> None:
        self.settings = settings
        self.normalizers = normalizers

    def _sample_from_request(self, request: ForwardPredictionRequest) -> InputSample:
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
        return InputSample(
            sample_name=request.sample_name,
            inlet1=float(request.inlet1),
            inlet2=float(request.inlet2),
            chips=chips,
        )

    def build_raw_graph(self, request: ForwardPredictionRequest) -> RawGraph:
        try:
            sample = self._sample_from_request(request)
            raw_x = build_raw_x(sample)
            raw_edge_index, raw_edge_attr = build_raw_edges(sample)
            raw_u = build_raw_u(sample)
            raw_chip_physics = build_raw_chip_physics(sample)
            node_type = build_node_type(sample)
            chip_physics_z = raw_chip_physics
            normalizers = getattr(self, "normalizers", None)
            if normalizers is not None:
                raw_x = normalize_tensor(raw_x, normalizers["x_mean"], normalizers["x_std"], "x")
                raw_edge_attr = normalize_tensor(raw_edge_attr, normalizers["edge_mean"], normalizers["edge_std"], "edge_attr")
                raw_u = normalize_tensor(raw_u, normalizers["u_mean"], normalizers["u_std"], "u")
                chip_physics_z = normalize_tensor(raw_chip_physics, normalizers["chip_physics_mean"], normalizers["chip_physics_std"], "chip_physics")
            return RawGraph(
                x=raw_x,
                edge_index=raw_edge_index,
                edge_attr=raw_edge_attr,
                u=raw_u,
                chip_physics=raw_chip_physics,
                chip_physics_z=chip_physics_z,
                node_type=node_type,
            )
        except Exception as exc:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_INPUT_SCHEMA_ERROR,
                "Failed to build Physics-GNN graph.",
                {"error": str(exc)},
            ) from exc
