from __future__ import annotations

from app.core.config import ForwardModelSettings
from app.core.errors import ModelRuntimeError
from app.model_runtime.forward_model import ForwardModelLoader
from app.model_runtime.graph_builder import GraphBuilder
from app.model_runtime.result_mapper import map_prediction_response
from app.schemas.forward import ForwardPredictionRequest, ForwardPredictionResponse


class ForwardModelAdapter:
    def __init__(self, settings: ForwardModelSettings | None = None) -> None:
        self.settings = settings or ForwardModelSettings.from_env()
        self.settings.validate_assets()
        loader = ForwardModelLoader(self.settings)
        self.models = loader.load_all()
        self.device = loader.device
        self.model_info = self.models[0]
        self.graph_builder = GraphBuilder(self.settings, self.model_info.normalizers)

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        try:
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
            )
            batch = Batch.from_data_list([graph]).to(self.device)
            with torch.inference_mode():
                output = self.model_info.model(batch)
            prediction = output["concentration"].detach().cpu().numpy()
            return map_prediction_response(request, prediction)
        except ModelRuntimeError:
            raise
