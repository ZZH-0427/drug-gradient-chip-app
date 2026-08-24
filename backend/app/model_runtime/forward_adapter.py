from __future__ import annotations

from typing import Protocol

from app.core.config import ForwardModelSettings
from app.core.errors import ModelRuntimeError
from app.model_runtime.fixed_six_forward_model import (
    EXPECTED_CHIP_COUNT,
    FixedSixGraphBuilder,
    clone_fixed_six_model,
)
from app.model_runtime.forward_model import ForwardModelLoader
from app.model_runtime.graph_builder import GraphBuilder
from app.model_runtime.result_mapper import map_prediction_response
from app.schemas.forward import ForwardPredictionRequest, ForwardPredictionResponse


class ForwardRuntime(Protocol):
    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        ...


class BaseForwardRuntime:
    def __init__(self, *, model_info, device, graph_builder) -> None:
        self.model_info = model_info
        self.device = device
        self.graph_builder = graph_builder

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        raw_graph = self.graph_builder.build_raw_graph(request)
        from torch_geometric.data import Batch, Data
        import torch

        graph = Data(
            x=raw_graph.x,
            edge_index=raw_graph.edge_index,
            edge_attr=raw_graph.edge_attr,
            u=raw_graph.u,
            chip_physics=raw_graph.chip_physics,
            chip_physics_z=raw_graph.chip_physics_z,
            node_type=raw_graph.node_type,
        )
        batch = Batch.from_data_list([graph]).to(self.device)
        with torch.inference_mode():
            output = self.model_info.model(batch)
        prediction = output["concentration"].detach().cpu().numpy()
        return map_prediction_response(request, prediction)


class ZeroShotForwardRuntime(BaseForwardRuntime):
    runtime_name = "zero-shot"


class FixedSixForwardRuntime(BaseForwardRuntime):
    runtime_name = "fixed-six"


class ForwardModelRouter:
    zero_shot_counts = frozenset({4, 5, 7, 8, 9, 10})

    def __init__(self, *, fixed_six: ForwardRuntime, zero_shot: ForwardRuntime) -> None:
        self.fixed_six = fixed_six
        self.zero_shot = zero_shot

    def route(self, chip_count: int) -> ForwardRuntime:
        if chip_count == EXPECTED_CHIP_COUNT:
            return self.fixed_six
        if chip_count in self.zero_shot_counts:
            return self.zero_shot
        raise ValueError(f"Unsupported chip_count: {chip_count}")

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        return self.route(request.chip_count).predict(request)


class ForwardModelAdapter:
    def __init__(self, settings: ForwardModelSettings | None = None) -> None:
        self.settings = settings or ForwardModelSettings.from_env()
        self.settings.validate_assets()
        loader = ForwardModelLoader(self.settings)
        self.models = loader.load_all()
        self.device = loader.device
        self.model_info = self.models[0]
        self.graph_builder = GraphBuilder(self.settings, self.model_info.normalizers)
        self.zero_shot_runtime = ZeroShotForwardRuntime(
            model_info=self.model_info,
            device=self.device,
            graph_builder=self.graph_builder,
        )
        self.fixed_six_model_info = clone_fixed_six_model(self.model_info, self.device)
        self.fixed_six_runtime = FixedSixForwardRuntime(
            model_info=self.fixed_six_model_info,
            device=self.device,
            graph_builder=FixedSixGraphBuilder(self.model_info.normalizers),
        )
        self.router = ForwardModelRouter(
            fixed_six=self.fixed_six_runtime,
            zero_shot=self.zero_shot_runtime,
        )

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        try:
            return self.router.predict(request)
        except ModelRuntimeError:
            raise
