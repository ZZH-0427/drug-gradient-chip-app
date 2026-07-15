from __future__ import annotations

from app.core.config import ForwardModelSettings
from app.core.errors import ModelRuntimeError
from app.model_runtime.ensemble import ForwardEnsemble
from app.model_runtime.forward_model import ForwardModelLoader
from app.model_runtime.graph_builder import GraphBuilder
from app.model_runtime.result_mapper import map_prediction_response
from app.schemas.forward import ForwardPredictionRequest, ForwardPredictionResponse


class ForwardModelAdapter:
    def __init__(self, settings: ForwardModelSettings | None = None) -> None:
        self.settings = settings or ForwardModelSettings.from_env()
        self.settings.validate_assets()
        self.graph_builder = GraphBuilder(self.settings)
        loader = ForwardModelLoader(self.settings)
        self.models = loader.load_all()
        self.ensemble = ForwardEnsemble(self.models, loader.device)

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        try:
            raw_graph = self.graph_builder.build_raw_graph(request)
            prediction = self.ensemble.predict(raw_graph)
            return map_prediction_response(request, prediction)
        except ModelRuntimeError:
            raise
