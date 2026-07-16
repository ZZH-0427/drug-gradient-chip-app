from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ModelErrorCode(StrEnum):
    MODEL_NOT_READY = "MODEL_NOT_READY"
    MODEL_CONFIGURATION_ERROR = "MODEL_CONFIGURATION_ERROR"
    FORWARD_INPUT_ERROR = "FORWARD_INPUT_ERROR"
    FORWARD_INFERENCE_ERROR = "FORWARD_INFERENCE_ERROR"
    MODEL_SOURCE_ROOT_MISSING = "MODEL_SOURCE_ROOT_MISSING"
    MODEL_ASSET_NOT_FOUND = "MODEL_ASSET_NOT_FOUND"
    MODEL_CHECKPOINT_INVALID = "MODEL_CHECKPOINT_INVALID"
    MODEL_INPUT_SCHEMA_ERROR = "MODEL_INPUT_SCHEMA_ERROR"
    MODEL_INFERENCE_FAILED = "MODEL_INFERENCE_FAILED"
    MODEL_OUTPUT_SCHEMA_ERROR = "MODEL_OUTPUT_SCHEMA_ERROR"


@dataclass
class ModelRuntimeError(Exception):
    code: ModelErrorCode
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


def wrap_runtime_error(
    code: ModelErrorCode,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> ModelRuntimeError:
    return ModelRuntimeError(code=code, message=message, details=details)
