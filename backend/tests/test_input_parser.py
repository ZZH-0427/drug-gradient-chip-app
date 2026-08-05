from __future__ import annotations

import pytest

from app.core.errors import ModelRuntimeError
from app.model_runtime.input_parser import parse_forward_csv


def test_parse_forward_csv_to_structured_request() -> None:
    requests = parse_forward_csv(
        __import__("pathlib").Path(__file__).with_name("fixtures_forward.csv")
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.sample_name == "DP 0"
    assert request.inlet1 == 1.0
    assert request.inlet2 == 0.0
    assert [chip.position for chip in request.chips_by_position()] == [1, 2, 3, 4, 5, 6]
    assert [chip.chip_type for chip in request.chips_by_position()] == [
        "5to4",
        "4to2",
        "1to6",
        "2to4",
        "6to3",
        "3to1",
    ]


def _dynamic_csv_text(chip_count: int) -> str:
    headers = ["sample_name", "inlet1", "inlet2"]
    row = [f"DP {chip_count}", "1.0", "0.0"]
    for point in range(1, chip_count * 2 + 1):
        chip_index = (point + 1) // 2
        headers.extend([f"P{point} 1to1 width", f"P{point} distance", f"P{point} position"])
        row.extend(["0.1", str(10 + point), str(chip_index)])
    return ",".join(headers) + "\n" + ",".join(row) + "\n"


def test_parse_forward_csv_accepts_ten_chip_p1_through_p20(tmp_path) -> None:
    path = tmp_path / "forward_10.csv"
    path.write_text(_dynamic_csv_text(10), encoding="utf-8")

    request = parse_forward_csv(path)[0]

    assert request.chip_count == 10
    assert len(request.chips) == 10
    assert request.chips[-1].position == 10


def test_parse_forward_csv_rejects_p21_tail_overflow(tmp_path) -> None:
    path = tmp_path / "forward_11.csv"
    path.write_text(_dynamic_csv_text(11), encoding="utf-8")

    with pytest.raises(ModelRuntimeError):
        parse_forward_csv(path)
