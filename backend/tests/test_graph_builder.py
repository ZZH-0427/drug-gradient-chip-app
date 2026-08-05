from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from app.model_runtime.graph_builder import GraphBuilder
from app.schemas.forward import ForwardPredictionRequest


def make_request(chip_count: int = 6) -> ForwardPredictionRequest:
    chip_types = ["5to4", "4to2", "1to6", "2to4", "6to3", "3to1", "1to1", "2to2", "3to3", "4to4"]
    return ForwardPredictionRequest(
        sample_name=f"DP {chip_count}",
        chip_count=chip_count,
        inlet1=1.0,
        inlet2=0.0,
        chips=[
            {
                "position": position,
                "chip_type": chip_types[position - 1],
                "left_width_mm": round(0.05 + 0.01 * position, 3),
                "right_width_mm": round(0.06 + 0.01 * position, 3),
                "left_bend_straight_distance_mm": 10 + position,
                "right_bend_straight_distance_mm": 20 + position,
            }
            for position in range(1, chip_count + 1)
        ],
    )


def test_graph_builder_generates_expected_raw_tensors() -> None:
    builder = GraphBuilder.__new__(GraphBuilder)
    left_widths = [0.261, 0.089, 0.212, 0.31, 0.187, 0.05]
    right_widths = [0.138, 0.04, 0.236, 0.163, 0.285, 0.114]

    request = ForwardPredictionRequest(
        sample_name="DP 0",
        inlet1=1.0,
        inlet2=0.0,
        chips=[
            {
                "position": position,
                "chip_type": f"{position}to{position}",
                "left_width_mm": left_widths[position - 1],
                "right_width_mm": right_widths[position - 1],
                "left_bend_straight_distance_mm": 10 + position,
                "right_bend_straight_distance_mm": 20 + position,
            }
            for position in range(1, 7)
        ],
    )

    graph = builder.build_raw_graph(request)

    assert tuple(graph.x.shape) == (8, 15)
    assert tuple(graph.edge_index.shape) == (2, 24)
    assert tuple(graph.edge_attr.shape) == (24, 9)
    assert tuple(graph.u.shape) == (1, 2)
    assert tuple(graph.chip_physics.shape) == (6, 7)
    assert tuple(graph.chip_physics_z.shape) == (6, 7)

    torch.testing.assert_close(
        graph.x[2:, 8],
        torch.tensor(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            dtype=graph.x.dtype,
            device=graph.x.device,
        ),
    )

    torch.testing.assert_close(
        graph.x[2:, 9],
        torch.tensor(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            dtype=graph.x.dtype,
            device=graph.x.device,
        ),
    )

    torch.testing.assert_close(
        graph.x[2:, 10],
        torch.tensor(
            [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            dtype=graph.x.dtype,
            device=graph.x.device,
        ),
        rtol=1e-6,
        atol=1e-7,
    )

    torch.testing.assert_close(
        graph.u,
        torch.tensor(
            [[1.0, 0.0]],
            dtype=graph.u.dtype,
            device=graph.u.device,
        ),
    )


@pytest.mark.parametrize("chip_count", [4, 5, 6, 7, 8, 9, 10])
def test_graph_builder_generates_dynamic_shapes(chip_count: int) -> None:
    builder = GraphBuilder.__new__(GraphBuilder)

    graph = builder.build_raw_graph(make_request(chip_count))

    assert tuple(graph.x.shape) == (chip_count + 2, 15)
    assert tuple(graph.edge_index.shape) == (2, 4 * chip_count)
    assert tuple(graph.edge_attr.shape) == (4 * chip_count, 9)
    assert tuple(graph.u.shape) == (1, 2)
    assert tuple(graph.chip_physics.shape) == (chip_count, 7)
    assert tuple(graph.chip_physics_z.shape) == (chip_count, 7)
    assert graph.node_type.tolist() == [0, 1] + [2] * chip_count


def test_six_chip_edge_order_matches_legacy_golden() -> None:
    builder = GraphBuilder.__new__(GraphBuilder)

    graph = builder.build_raw_graph(make_request(6))

    assert graph.edge_index.tolist() == [
        [0, 1, 2, 2, 0, 1, 3, 3, 0, 1, 4, 4, 0, 1, 5, 5, 0, 1, 6, 6, 0, 1, 7, 7],
        [2, 2, 0, 1, 3, 3, 0, 1, 4, 4, 0, 1, 5, 5, 0, 1, 6, 6, 0, 1, 7, 7, 0, 1],
    ]


@pytest.mark.parametrize(("chip_count", "left_width", "right_width"), [(9, 0.29, 0.3), (10, 0.3, 0.31)])
def test_tail_chip_participates_in_graph_features(chip_count: int, left_width: float, right_width: float) -> None:
    builder = GraphBuilder.__new__(GraphBuilder)
    request = make_request(chip_count)
    tail = request.chips[-1]
    tail.left_width_mm = left_width
    tail.right_width_mm = right_width

    graph = builder.build_raw_graph(request)

    tail_node_index = chip_count + 1
    assert float(graph.x[tail_node_index, 4]) == pytest.approx(left_width)
    assert float(graph.x[tail_node_index, 5]) == pytest.approx(right_width)
    assert float(graph.edge_attr[-4, 0]) == pytest.approx(left_width)
    assert float(graph.edge_attr[-3, 0]) == pytest.approx(right_width)
