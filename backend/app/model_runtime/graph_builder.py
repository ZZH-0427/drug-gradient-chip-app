from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor

from app.core.config import ForwardModelSettings
from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.schemas.forward import ForwardPredictionRequest


EXPECTED_NODE_FEATURE_NAMES = [
    "left_width_mm",
    "right_width_mm",
    "left_bend_straight_distance_mm",
    "right_bend_straight_distance_mm",
    "left_position",
    "right_position",
    "node_position_norm",
]
EXPECTED_EDGE_FEATURE_NAMES = ["signed_position_delta", "absolute_position_delta"]


@dataclass(frozen=True)
class RawGraph:
    x: Tensor
    edge_index: Tensor
    edge_attr: Tensor
    u: Tensor


def safe_torch_load(path: Path) -> Any:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def _payload_graphs(payload: Any) -> tuple[dict[str, Any], list[Any]]:
    if isinstance(payload, Mapping):
        graphs = payload.get("graphs")
        if graphs is None:
            raise KeyError("physics_gnn_dataset.pt does not contain graphs")
        return dict(payload), list(graphs)
    if isinstance(payload, (list, tuple)):
        return {}, list(payload)
    raise TypeError(f"Unsupported dataset payload type: {type(payload).__name__}")


def _first_valid_graph(graphs: Sequence[Any]) -> Any:
    for graph in graphs:
        if (
            torch.is_tensor(getattr(graph, "x", None))
            and torch.is_tensor(getattr(graph, "edge_index", None))
            and torch.is_tensor(getattr(graph, "edge_attr", None))
        ):
            return graph
    raise ValueError("No valid graph found in physics_gnn_dataset.pt")


def _name_list(payload: Mapping[str, Any], graph: Any, keys: Sequence[str]) -> list[str]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            value = getattr(graph, key, None)
        if value is None:
            continue
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        try:
            result = [str(item).strip() for item in list(value)]
        except TypeError:
            continue
        if result:
            return result
    return []


class GraphBuilder:
    def __init__(self, settings: ForwardModelSettings) -> None:
        self.settings = settings
        self.edge_index: Tensor
        self.edge_attr: Tensor
        self.node_feature_names: list[str]
        self.edge_feature_names: list[str]
        self._load_template()

    def _load_template(self) -> None:
        if not self.settings.dataset_path.exists():
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "physics_gnn_dataset.pt was not found.",
                {"path": str(self.settings.dataset_path)},
            )
        try:
            payload, graphs = _payload_graphs(safe_torch_load(self.settings.dataset_path))
            graph = _first_valid_graph(graphs)
            self.edge_index = graph.edge_index.detach().cpu().long()
            self.edge_attr = graph.edge_attr.detach().cpu().float()
            self.node_feature_names = _name_list(payload, graph, ("node_feature_names", "x_feature_names"))
            self.edge_feature_names = _name_list(payload, graph, ("edge_feature_names",))
            if not self.node_feature_names and self.settings.dataset_summary_path.exists():
                summary = json.loads(self.settings.dataset_summary_path.read_text(encoding="utf-8"))
                self.node_feature_names = list(summary.get("node_feature_names", []))
                self.edge_feature_names = list(summary.get("edge_feature_names", []))
            self._validate_template(graph)
        except ModelRuntimeError:
            raise
        except Exception as exc:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_ASSET_NOT_FOUND,
                "Failed to load graph template.",
                {"path": str(self.settings.dataset_path), "error": str(exc)},
            ) from exc

    def _validate_template(self, graph: Any) -> None:
        x = graph.x.detach().cpu()
        if x.shape[0] != 6 or x.shape[1] != 7:
            raise ValueError(f"Template graph x shape must be [6, 7], got {tuple(x.shape)}")
        if tuple(self.edge_index.shape) != (2, 10):
            raise ValueError(f"edge_index shape must be [2, 10], got {tuple(self.edge_index.shape)}")
        if tuple(self.edge_attr.shape) != (10, 2):
            raise ValueError(f"edge_attr shape must be [10, 2], got {tuple(self.edge_attr.shape)}")
        if self.node_feature_names and self.node_feature_names != EXPECTED_NODE_FEATURE_NAMES:
            raise ValueError(f"node_feature_names mismatch: {self.node_feature_names}")
        if self.edge_feature_names and self.edge_feature_names != EXPECTED_EDGE_FEATURE_NAMES:
            raise ValueError(f"edge_feature_names mismatch: {self.edge_feature_names}")

    def build_raw_graph(self, request: ForwardPredictionRequest) -> RawGraph:
        rows: list[list[float]] = []
        for chip in request.chips_by_position():
            position = float(chip.position)
            rows.append(
                [
                    float(chip.left_width_mm),
                    float(chip.right_width_mm),
                    float(chip.left_bend_straight_distance_mm),
                    float(chip.right_bend_straight_distance_mm),
                    position,
                    position,
                    (position - 1.0) / 5.0,
                ]
            )

        return RawGraph(
            x=torch.tensor(rows, dtype=torch.float32),
            edge_index=self.edge_index.clone(),
            edge_attr=self.edge_attr.clone(),
            u=torch.tensor([[float(request.inlet1), float(request.inlet2)]], dtype=torch.float32),
        )
