from __future__ import annotations

import math
from typing import Any


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

        position: int = Field(ge=1, le=6)
        chip_type: str = Field(min_length=1)
        left_width_mm: float
        right_width_mm: float
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
        inlet1: float
        inlet2: float
        chips: list[ForwardChipInput]

        @field_validator("inlet1", "inlet2", mode="before")
        @classmethod
        def finite_inlet(cls, value: Any) -> float:
            return _finite_float(value, "inlet")

        @model_validator(mode="after")
        def validate_chips(self) -> "ForwardPredictionRequest":
            if len(self.chips) != 6:
                raise ValueError("chips must contain exactly 6 items")
            positions = [chip.position for chip in self.chips]
            if sorted(positions) != [1, 2, 3, 4, 5, 6]:
                raise ValueError("chips positions must be exactly 1 through 6 without duplicates")
            return self

        def chips_by_position(self) -> list[ForwardChipInput]:
            return sorted(self.chips, key=lambda chip: chip.position)


    class ForwardPredictionItem(BaseModel):
        model_config = ConfigDict(extra="forbid")

        position: int
        point: str
        chip_type: str
        mean: float
        std: float
        seed_values: dict[str, float]


    class ForwardPredictionResponse(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sample_name: str
        inlets: dict[str, float]
        ensemble_seeds: list[int]
        predictions: list[ForwardPredictionItem]

        @model_validator(mode="after")
        def validate_predictions(self) -> "ForwardPredictionResponse":
            if len(self.predictions) != 6:
                raise ValueError("predictions must contain exactly 6 items")
            for index, item in enumerate(self.predictions, start=1):
                if item.position != index or item.point != f"y{index}":
                    raise ValueError("predictions must be ordered by position y1..y6")
                values = [item.mean, item.std, *item.seed_values.values()]
                if any(not math.isfinite(float(value)) for value in values):
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
            if self.position < 1 or self.position > 6:
                raise ValueError("position must be 1 through 6")
            self.chip_type = str(chip_type).strip()
            if not self.chip_type:
                raise ValueError("chip_type must not be empty")
            self.left_width_mm = _finite_float(left_width_mm, "left_width_mm")
            self.right_width_mm = _finite_float(right_width_mm, "right_width_mm")
            self.left_bend_straight_distance_mm = _finite_float(
                left_bend_straight_distance_mm,
                "left_bend_straight_distance_mm",
            )
            self.right_bend_straight_distance_mm = _finite_float(
                right_bend_straight_distance_mm,
                "right_bend_straight_distance_mm",
            )


    class ForwardPredictionRequest(_DumpMixin):
        def __init__(self, *, sample_name: str, inlet1: Any, inlet2: Any, chips: list[Any]) -> None:
            self.sample_name = str(sample_name).strip()
            if not self.sample_name:
                raise ValueError("sample_name must not be empty")
            self.inlet1 = _finite_float(inlet1, "inlet1")
            self.inlet2 = _finite_float(inlet2, "inlet2")
            self.chips = [
                chip if isinstance(chip, ForwardChipInput) else ForwardChipInput(**chip)
                for chip in chips
            ]
            if len(self.chips) != 6:
                raise ValueError("chips must contain exactly 6 items")
            positions = [chip.position for chip in self.chips]
            if sorted(positions) != [1, 2, 3, 4, 5, 6]:
                raise ValueError("chips positions must be exactly 1 through 6 without duplicates")

        def chips_by_position(self) -> list[ForwardChipInput]:
            return sorted(self.chips, key=lambda chip: chip.position)


    class ForwardPredictionItem(_DumpMixin):
        def __init__(
            self,
            *,
            position: int,
            point: str,
            chip_type: str,
            mean: Any,
            std: Any,
            seed_values: dict[str, Any],
        ) -> None:
            self.position = int(position)
            self.point = str(point)
            self.chip_type = str(chip_type)
            self.mean = _finite_float(mean, "mean")
            self.std = _finite_float(std, "std")
            self.seed_values = {
                str(seed): _finite_float(value, f"seed_{seed}")
                for seed, value in seed_values.items()
            }


    class ForwardPredictionResponse(_DumpMixin):
        def __init__(
            self,
            *,
            sample_name: str,
            inlets: dict[str, Any],
            ensemble_seeds: list[int],
            predictions: list[Any],
        ) -> None:
            self.sample_name = str(sample_name)
            self.inlets = {key: _finite_float(value, key) for key, value in inlets.items()}
            self.ensemble_seeds = [int(seed) for seed in ensemble_seeds]
            self.predictions = [
                item if isinstance(item, ForwardPredictionItem) else ForwardPredictionItem(**item)
                for item in predictions
            ]
            if len(self.predictions) != 6:
                raise ValueError("predictions must contain exactly 6 items")
            for index, item in enumerate(self.predictions, start=1):
                if item.position != index or item.point != f"y{index}":
                    raise ValueError("predictions must be ordered by position y1..y6")
