from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str


class ModelStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    model_name: str
    ensemble_size: int
    seeds: list[int]
    device: str
