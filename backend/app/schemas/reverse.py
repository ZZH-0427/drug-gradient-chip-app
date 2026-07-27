from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReverseTaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


def _finite_float(value: Any, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


class ReverseDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inlet1: float
    inlet2: float
    target_concentrations: list[float] = Field(min_length=6, max_length=6)

    @field_validator("inlet1", "inlet2", mode="before")
    @classmethod
    def finite_inlet(cls, value: Any) -> float:
        return _finite_float(value, "inlet")

    @field_validator("target_concentrations", mode="before")
    @classmethod
    def finite_targets(cls, value: Any) -> list[float]:
        if not isinstance(value, list):
            raise ValueError("target_concentrations must be a list")
        return [_finite_float(item, "target_concentration") for item in value]

    @model_validator(mode="after")
    def validate_inlets(self) -> "ReverseDesignRequest":
        if abs(float(self.inlet1) - float(self.inlet2)) < 1.0e-12:
            raise ValueError("inlet1 and inlet2 must be different")
        return self


class ReverseTaskCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: ReverseTaskStatus


class ReverseDesignChipResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    point_labels: list[str]
    chip_type: str
    left_width_mm: float
    right_width_mm: float
    left_bend_class: int
    right_bend_class: int
    left_distance_mm: float
    right_distance_mm: float
    target_concentration: float
    predicted_concentration: float
    absolute_error: float


class ReverseDesignMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mae: float
    rmse: float
    maxae: float
    spearman: float
    internal_screening_pass: bool
    selected_restart: int


class ReverseDesignResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inlet1: float
    inlet2: float
    target_concentrations: list[float]
    chips: list[ReverseDesignChipResult]
    metrics: ReverseDesignMetrics
    warnings: list[str]
    notes: list[str]


class ReverseTaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: ReverseTaskStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    result: ReverseDesignResult | None = None
    error: dict[str, str] | None = None
    warnings: list[str] = Field(default_factory=list)
