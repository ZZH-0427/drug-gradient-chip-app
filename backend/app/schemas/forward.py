from __future__ import annotations

import math
from typing import Any

from app.core.chip_count import CURRENT_MODEL_CHIP_COUNT, MAX_CHIP_COUNT, MIN_CHIP_COUNT

FORWARD_WIDTH_MIN_MM = 0.04
FORWARD_WIDTH_MAX_MM = 0.31


def _finite_float(value: Any, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
except ModuleNotFoundError:
    BaseModel = object  # type: ignore[assignment,misc]
    ConfigDict = None  # type: ignore[assignment]
    Field = None  # type: ignore[assignment]
    field_validator = None  # type: ignore[assignment]
    model_validator = None  # type: ignore[assignment]


if Field is not None:

    class ForwardChipInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

        position: int = Field(ge=1, le=MAX_CHIP_COUNT)
        chip_type: str = Field(min_length=1)
        left_width_mm: float = Field(ge=FORWARD_WIDTH_MIN_MM, le=FORWARD_WIDTH_MAX_MM)
        right_width_mm: float = Field(ge=FORWARD_WIDTH_MIN_MM, le=FORWARD_WIDTH_MAX_MM)
        left_bend_straight_distance_mm: float
        right_bend_straight_distance_mm: float

        @field_validator(
            "left_width_mm",
            "right_width_mm",
            "left_bend_straight_distance_mm",
            "right_bend_straight_distance_mm",
            mode="before",
        )
        @classmethod
        def finite_measurement(cls, value: Any) -> float:
            return _finite_float(value, "chip measurement")


    class ForwardPredictionRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sample_name: str = Field(min_length=1)
        chip_count: int = Field(default=CURRENT_MODEL_CHIP_COUNT, ge=MIN_CHIP_COUNT, le=MAX_CHIP_COUNT)
        inlet1: float
        inlet2: float
        chips: list[ForwardChipInput]

        @field_validator("inlet1", "inlet2", mode="before")
        @classmethod
        def finite_inlet(cls, value: Any) -> float:
            return _finite_float(value, "inlet")

        @model_validator(mode="after")
        def validate_chips(self) -> "ForwardPredictionRequest":
            if len(self.chips) != self.chip_count:
                raise ValueError("chips length must equal chip_count")
            positions = [chip.position for chip in self.chips]
            expected_positions = list(range(1, self.chip_count + 1))
            if sorted(positions) != expected_positions:
                raise ValueError("chips positions must be consecutive from 1 through chip_count without duplicates")
            return self

        def chips_by_position(self) -> list[ForwardChipInput]:
            return sorted(self.chips, key=lambda chip: chip.position)


    class ForwardPredictionItem(BaseModel):
        model_config = ConfigDict(extra="forbid")

        position: int
        point: str
        chip_type: str
        concentration: float


    class ForwardPredictionResponse(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sample_name: str
        inlets: dict[str, float]
        chip_count: int
        predictions: list[ForwardPredictionItem]

        @model_validator(mode="after")
        def validate_predictions(self) -> "ForwardPredictionResponse":
            if len(self.predictions) != self.chip_count:
                raise ValueError("predictions length must equal chip_count")
            for index, item in enumerate(self.predictions, start=1):
                if item.position != index or item.point != f"y{index}":
                    raise ValueError("predictions must be ordered by position")
                if not math.isfinite(float(item.concentration)):
                    raise ValueError("prediction values must be finite")
            return self

else:

    class _DumpMixin:
        def model_dump(self) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in self.__dict__.items():
                if isinstance(value, list):
                    result[key] = [
                        item.model_dump() if hasattr(item, "model_dump") else item
                        for item in value
                    ]
                elif hasattr(value, "model_dump"):
                    result[key] = value.model_dump()
                else:
                    result[key] = value
            return result


    class ForwardChipInput(_DumpMixin):
        def __init__(
            self,
            *,
            position: int,
            chip_type: str,
            left_width_mm: Any,
            right_width_mm: Any,
            left_bend_straight_distance_mm: Any,
            right_bend_straight_distance_mm: Any,
        ) -> None:
            self.position = int(position)
            if self.position < 1 or self.position > MAX_CHIP_COUNT:
                raise ValueError("position must be 1 through 10")
            self.chip_type = str(chip_type).strip()
            if not self.chip_type:
                raise ValueError("chip_type must not be empty")
            self.left_width_mm = _finite_float(left_width_mm, "left_width_mm")
            self.right_width_mm = _finite_float(right_width_mm, "right_width_mm")
            if self.left_width_mm < FORWARD_WIDTH_MIN_MM or self.left_width_mm > FORWARD_WIDTH_MAX_MM:
                raise ValueError("left_width_mm must be between 0.04 and 0.31")
            if self.right_width_mm < FORWARD_WIDTH_MIN_MM or self.right_width_mm > FORWARD_WIDTH_MAX_MM:
                raise ValueError("right_width_mm must be between 0.04 and 0.31")
            self.left_bend_straight_distance_mm = _finite_float(
                left_bend_straight_distance_mm,
                "left_bend_straight_distance_mm",
            )
            self.right_bend_straight_distance_mm = _finite_float(
                right_bend_straight_distance_mm,
                "right_bend_straight_distance_mm",
            )


    class ForwardPredictionRequest(_DumpMixin):
        def __init__(
            self,
            *,
            sample_name: str,
            inlet1: Any,
            inlet2: Any,
            chips: list[Any],
            chip_count: Any = CURRENT_MODEL_CHIP_COUNT,
        ) -> None:
            self.sample_name = str(sample_name).strip()
            if not self.sample_name:
                raise ValueError("sample_name must not be empty")
            self.chip_count = int(chip_count)
            if self.chip_count < MIN_CHIP_COUNT or self.chip_count > MAX_CHIP_COUNT:
                raise ValueError("chip_count must be between 4 and 10")
            self.inlet1 = _finite_float(inlet1, "inlet1")
            self.inlet2 = _finite_float(inlet2, "inlet2")
            self.chips = [
                chip if isinstance(chip, ForwardChipInput) else ForwardChipInput(**chip)
                for chip in chips
            ]
            if len(self.chips) != self.chip_count:
                raise ValueError("chips length must equal chip_count")
            positions = [chip.position for chip in self.chips]
            if sorted(positions) != list(range(1, self.chip_count + 1)):
                raise ValueError("chips positions must be consecutive from 1 through chip_count without duplicates")

        def chips_by_position(self) -> list[ForwardChipInput]:
            return sorted(self.chips, key=lambda chip: chip.position)


    class ForwardPredictionItem(_DumpMixin):
        def __init__(
            self,
            *,
            position: int,
            point: str,
            chip_type: str,
            concentration: Any,
        ) -> None:
            self.position = int(position)
            self.point = str(point)
            self.chip_type = str(chip_type)
            self.concentration = _finite_float(concentration, "concentration")


    class ForwardPredictionResponse(_DumpMixin):
        def __init__(
            self,
            *,
            sample_name: str,
            inlets: dict[str, Any],
            chip_count: int,
            predictions: list[Any],
        ) -> None:
            self.sample_name = str(sample_name)
            self.inlets = {key: _finite_float(value, key) for key, value in inlets.items()}
            self.chip_count = int(chip_count)
            self.predictions = [
                item if isinstance(item, ForwardPredictionItem) else ForwardPredictionItem(**item)
                for item in predictions
            ]
            if len(self.predictions) != self.chip_count:
                raise ValueError("predictions length must equal chip_count")
            for index, item in enumerate(self.predictions, start=1):
                if item.position != index or item.point != f"y{index}":
                    raise ValueError("predictions must be ordered by position")
