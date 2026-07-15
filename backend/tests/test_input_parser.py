from __future__ import annotations

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
