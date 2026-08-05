from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from app.core.errors import ModelErrorCode, ModelRuntimeError
from app.core.chip_count import MAX_CHIP_COUNT, MIN_CHIP_COUNT
from app.schemas.forward import ForwardChipInput, ForwardPredictionRequest


P_COLUMN_PATTERN = re.compile(r"^\s*p\s*(\d+)(?:\D|$)", re.IGNORECASE)
CHANNEL_PATTERN = re.compile(r"(?:outlet\s*)?(\d+)\s*to\s*(\d+)", re.IGNORECASE)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def normalized_name(value: Any) -> str:
    text = clean_text(value).lower()
    text = text.replace("毫米", "mm")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def as_float(value: Any, display_name: str) -> float:
    text = clean_text(value).replace(",", "")
    if not text:
        raise ValueError(f"{display_name} is empty")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"{display_name} is not finite")
    return number


def read_table_without_header(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_error: UnicodeDecodeError | None = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return pd.read_csv(
                    path,
                    header=None,
                    dtype=object,
                    encoding=encoding,
                    keep_default_na=False,
                )
            except UnicodeDecodeError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=None, dtype=object, keep_default_na=False)
    raise ValueError(f"Unsupported input format: {path.suffix}")


def _is_distance_header(value: Any) -> bool:
    name = normalized_name(value)
    return "距离" in name or "distance" in name or "length" in name or "path" in name


def _is_position_header(value: Any) -> bool:
    name = normalized_name(value)
    return "位置" in name or "position" in name


def _parse_channel_name_from_header(value: Any) -> str:
    match = CHANNEL_PATTERN.search(clean_text(value))
    if not match:
        return ""
    return f"{int(match.group(1))}to{int(match.group(2))}"


def locate_columns(headers: Sequence[Any]) -> dict[str, Any]:
    inlet1_index: int | None = None
    inlet2_index: int | None = None
    p_width_columns: dict[int, int] = {}

    for index, header in enumerate(headers):
        name = normalized_name(header)
        if name in {"inlet1", "inlet1concentration", "入口1", "入口1浓度"}:
            inlet1_index = index
        if name in {"inlet2", "inlet2concentration", "入口2", "入口2浓度"}:
            inlet2_index = index

        match = P_COLUMN_PATTERN.match(clean_text(header))
        if match:
            if _is_distance_header(header) or _is_position_header(header):
                continue
            p_number = int(match.group(1))
            if p_number > MAX_CHIP_COUNT * 2:
                raise ValueError(f"Input table contains unsupported tail point P{p_number}")
            p_width_columns[p_number] = index

    if inlet1_index is None or inlet2_index is None:
        raise ValueError("Input table must contain inlet1 and inlet2 columns")

    if not p_width_columns:
        raise ValueError("Input table must contain P width columns")
    max_p_number = max(p_width_columns)
    if max_p_number % 2:
        raise ValueError("Input table must contain complete P pairs")
    chip_count = max_p_number // 2
    if chip_count < MIN_CHIP_COUNT or chip_count > MAX_CHIP_COUNT:
        raise ValueError("chip_count must be between 4 and 10")

    missing_p = [number for number in range(1, max_p_number + 1) if number not in p_width_columns]
    if missing_p:
        raise ValueError("Input table is missing width columns: " + ", ".join(f"P{n}" for n in missing_p))

    p_columns: dict[int, dict[str, Any]] = {}
    for p_number in range(1, max_p_number + 1):
        width_index = p_width_columns[p_number]
        next_indexes = [idx for number, idx in p_width_columns.items() if idx > width_index]
        stop_index = min(next_indexes) if next_indexes else len(headers)

        distance_index: int | None = None
        position_index: int | None = None
        for index in range(width_index + 1, stop_index):
            if distance_index is None and _is_distance_header(headers[index]):
                distance_index = index
            if position_index is None and _is_position_header(headers[index]):
                position_index = index

        if distance_index is None and width_index + 1 < len(headers):
            distance_index = width_index + 1
        if position_index is None and width_index + 2 < len(headers):
            position_index = width_index + 2
        if distance_index is None or position_index is None:
            raise ValueError(f"Could not locate distance and position columns after P{p_number}")

        p_columns[p_number] = {
            "width": width_index,
            "distance": distance_index,
            "position": position_index,
            "channel": _parse_channel_name_from_header(headers[width_index]),
        }

    return {"name": 0, "inlet1": inlet1_index, "inlet2": inlet2_index, "p": p_columns, "chip_count": chip_count}


def _row_is_description(row: Sequence[Any]) -> bool:
    first = normalized_name(row[0] if row else "")
    if first in {"名称", "name", "样本", "samplename"}:
        return True
    tokens = {normalized_name(value) for value in row if clean_text(value)}
    return "p1" in tokens and any(f"p{number}" in tokens for number in range(8, MAX_CHIP_COUNT * 2 + 1, 2))


def parse_forward_csv(path: Path) -> list[ForwardPredictionRequest]:
    try:
        dataframe = read_table_without_header(path)
        if dataframe.empty or len(dataframe.index) < 2:
            raise ValueError("Input table has no data rows")

        headers = dataframe.iloc[0].tolist()
        columns = locate_columns(headers)
        requests: list[ForwardPredictionRequest] = []

        for row_index in range(1, len(dataframe.index)):
            row = dataframe.iloc[row_index].tolist()
            if not any(clean_text(value) for value in row):
                continue
            if _row_is_description(row):
                continue

            sample_name = clean_text(row[columns["name"]]) or f"sample_{row_index}"
            chips: list[ForwardChipInput] = []

            chip_count = int(columns["chip_count"])
            for node_index in range(chip_count):
                left_p = node_index * 2 + 1
                right_p = left_p + 1
                left_columns = columns["p"][left_p]
                right_columns = columns["p"][right_p]
                expected_position = node_index + 1

                left_position = as_float(row[left_columns["position"]], f"{sample_name}.P{left_p}.position")
                right_position = as_float(row[right_columns["position"]], f"{sample_name}.P{right_p}.position")
                if abs(left_position - expected_position) > 1e-6:
                    raise ValueError(f"{sample_name}.P{left_p} position must be {expected_position}")
                if abs(right_position - expected_position) > 1e-6:
                    raise ValueError(f"{sample_name}.P{right_p} position must be {expected_position}")

                chip_type = clean_text(left_columns.get("channel", ""))
                right_chip_type = clean_text(right_columns.get("channel", ""))
                if not chip_type or not right_chip_type:
                    raise ValueError(f"{sample_name}.P{left_p}/P{right_p} chip type was not parsed")
                if chip_type != right_chip_type:
                    raise ValueError(f"{sample_name}.P{left_p}/P{right_p} chip types differ")

                chips.append(
                    ForwardChipInput(
                        position=expected_position,
                        chip_type=chip_type,
                        left_width_mm=as_float(row[left_columns["width"]], f"{sample_name}.P{left_p}.width"),
                        right_width_mm=as_float(row[right_columns["width"]], f"{sample_name}.P{right_p}.width"),
                        left_bend_straight_distance_mm=as_float(
                            row[left_columns["distance"]],
                            f"{sample_name}.P{left_p}.distance",
                        ),
                        right_bend_straight_distance_mm=as_float(
                            row[right_columns["distance"]],
                            f"{sample_name}.P{right_p}.distance",
                        ),
                    )
                )

            requests.append(
                ForwardPredictionRequest(
                    sample_name=sample_name,
                    chip_count=chip_count,
                    inlet1=as_float(row[columns["inlet1"]], f"{sample_name}.inlet1"),
                    inlet2=as_float(row[columns["inlet2"]], f"{sample_name}.inlet2"),
                    chips=chips,
                )
            )

        if not requests:
            raise ValueError("Input table has no valid prediction rows")
        return requests
    except ModelRuntimeError:
        raise
    except Exception as exc:
        raise ModelRuntimeError(
            ModelErrorCode.MODEL_INPUT_SCHEMA_ERROR,
            "Failed to parse forward prediction input.",
            {"path": str(path), "error": str(exc)},
        ) from exc
