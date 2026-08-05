from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.chip_count import MAX_CHIP_COUNT, MIN_CHIP_COUNT
from app.schemas.forward import ForwardPredictionRequest, ForwardPredictionResponse


FORWARD_SUPPORTED_CHIP_COUNTS = list(range(MIN_CHIP_COUNT, MAX_CHIP_COUNT + 1))
REVERSE_SUPPORTED_CHIP_COUNTS = [6]


class ForwardAdapterProtocol(Protocol):
    settings: object
    models: list[object]
    device: object

    def predict(self, request: ForwardPredictionRequest) -> ForwardPredictionResponse:
        ...


@dataclass
class ForwardModelState:
    ready: bool = False
    adapter: ForwardAdapterProtocol | None = None
    error_code: str | None = None
    error_message: str | None = None
    model_name: str = "physics-gnn"
    supported_chip_counts: list[int] | None = None
    public_output: str = "concentration"
    device: str = "unknown"

    @classmethod
    def not_ready(cls, *, code: str | None = None, message: str | None = None) -> "ForwardModelState":
        return cls(
            ready=False,
            error_code=code,
            error_message=message,
            supported_chip_counts=FORWARD_SUPPORTED_CHIP_COUNTS,
        )

    @classmethod
    def ready_state(cls, adapter: ForwardAdapterProtocol) -> "ForwardModelState":
        device = "unknown"
        if getattr(adapter, "device", None) is not None:
            device = str(getattr(adapter, "device", "unknown"))
        return cls(
            ready=True,
            adapter=adapter,
            supported_chip_counts=FORWARD_SUPPORTED_CHIP_COUNTS,
            device=device,
        )
