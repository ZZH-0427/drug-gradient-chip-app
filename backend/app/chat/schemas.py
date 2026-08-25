from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.forward import ForwardPredictionResponse
from app.schemas.reverse import ReverseTaskCreatedResponse


ChatLanguage = Literal["zh-CN", "en", "en-US"]
ChatMode = Literal["idle", "forward", "reverse"]
ChatState = Literal["idle", "collecting", "ready_for_confirmation", "running", "completed", "error"]
ChatIntent = Literal[
    "unknown",
    "start_forward",
    "start_reverse",
    "set_chip_count",
    "set_inlet",
    "set_chip_parameter",
    "set_target_concentration",
    "show_parameters",
    "confirm",
    "run_prediction",
    "cancel",
    "reset",
    "help",
    "switch_language",
]


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    message: str = Field(min_length=1)
    language: ChatLanguage = "zh-CN"

    @field_validator("session_id", "message", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ChatError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ChatConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ChatMode
    summary: dict[str, Any]


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    state: ChatState
    intent: ChatIntent
    assistant_message: str
    missing_fields: list[str] = Field(default_factory=list)
    parameter_summary: dict[str, Any] = Field(default_factory=dict)
    confirmation: ChatConfirmation | None = None
    forward_prediction: ForwardPredictionResponse | None = None
    reverse_task: ReverseTaskCreatedResponse | None = None
    error: ChatError | None = None
