from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import DEFAULT_SEEDS
from app.schemas.forward import ForwardPredictionRequest, ForwardPredictionResponse


class ForwardAdapterProtocol(Protocol):
    settings: object
    models: list[object]
    ensemble: object

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        ...


@dataclass
class ForwardModelState:
    ready: bool = False
    adapter: ForwardAdapterProtocol | None = None
    error_code: str | None = None
    error_message: str | None = None
    model_name: str = "forward-ensemble"
    seeds: list[int] | None = None
    device: str = "unknown"

    @classmethod
    def not_ready(cls, *, code: str | None = None, message: str | None = None) -> "ForwardModelState":
        return cls(
            ready=False,
            error_code=code,
            error_message=message,
            seeds=list(DEFAULT_SEEDS),
        )

    @classmethod
    def ready_state(cls, adapter: ForwardAdapterProtocol) -> "ForwardModelState":
        seeds = [int(getattr(model, "seed")) for model in getattr(adapter, "models", [])]
        if not seeds:
            seeds = list(DEFAULT_SEEDS)
        device = "unknown"
        ensemble = getattr(adapter, "ensemble", None)
        if ensemble is not None:
            device = str(getattr(ensemble, "device", "unknown"))
        return cls(
            ready=True,
            adapter=adapter,
            seeds=seeds,
            device=device,
        )
