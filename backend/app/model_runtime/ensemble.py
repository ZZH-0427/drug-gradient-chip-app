from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch
from torch import Tensor
from torch_geometric.data import Batch, Data

from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.model_runtime.forward_model import LoadedForwardModel
from app.model_runtime.graph_builder import RawGraph


EXPECTED_OUTPUT_DIM = 6


@dataclass(frozen=True)
class EnsemblePrediction:
    mean: np.ndarray
    std: np.ndarray
    seed_predictions: dict[int, np.ndarray]


def normalize_tensor(value: Tensor, mean: Tensor, std: Tensor, display_name: str) -> Tensor:
    mean = mean.detach().cpu().float()
    std = std.detach().cpu().float()
    if value.shape[-1] != mean.numel():
        raise ValueError(f"{display_name} dimension mismatch: {value.shape[-1]} vs {mean.numel()}")
    safe_std = torch.where(std.abs() < 1e-12, torch.ones_like(std), std)
    return (value.float() - mean) / safe_std


class ForwardEnsemble:
    def __init__(self, models: Sequence[LoadedForwardModel], device: torch.device) -> None:
        if not models:
            raise ModelRuntimeError(ModelErrorCode.MODEL_CHECKPOINT_INVALID, "No forward models were loaded.")
        self.models = list(models)
        self.device = device

    def _batch_for_model(self, raw_graph: RawGraph, model_info: LoadedForwardModel) -> Batch:
        normalizers = model_info.normalizers
        graph = Data(
            x=normalize_tensor(raw_graph.x, normalizers["x_mean"], normalizers["x_std"], "x"),
            edge_index=raw_graph.edge_index.clone(),
            edge_attr=normalize_tensor(
                raw_graph.edge_attr,
                normalizers["edge_mean"],
                normalizers["edge_std"],
                "edge_attr",
            ).clone(),
            u=normalize_tensor(raw_graph.u, normalizers["u_mean"], normalizers["u_std"], "u"),
        )
        return Batch.from_data_list([graph]).to(self.device)

    def predict(self, raw_graph: RawGraph) -> EnsemblePrediction:
        try:
            seed_predictions: dict[int, np.ndarray] = {}
            with torch.inference_mode():
                for model_info in self.models:
                    batch = self._batch_for_model(raw_graph, model_info)
                    prediction = model_info.model(batch).detach().cpu().numpy().astype(np.float64)
                    if prediction.shape != (1, EXPECTED_OUTPUT_DIM):
                        raise ValueError(f"seed={model_info.seed} output shape was {prediction.shape}")
                    seed_predictions[model_info.seed] = prediction

            stacked = np.stack([seed_predictions[seed] for seed in sorted(seed_predictions)], axis=0)
            return EnsemblePrediction(
                mean=stacked.mean(axis=0),
                std=stacked.std(axis=0, ddof=0),
                seed_predictions=seed_predictions,
            )
        except ModelRuntimeError:
            raise
        except Exception as exc:
            raise ModelRuntimeError(
                ModelErrorCode.MODEL_INFERENCE_FAILED,
                "Forward model inference failed.",
                {"error": str(exc)},
            ) from exc
