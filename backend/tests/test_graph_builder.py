from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from app.model_runtime.graph_builder import GraphBuilder
from app.schemas.forward import ForwardPredictionRequest


def test_graph_builder_generates_expected_raw_tensors() -> None:
    builder = GraphBuilder.__new__(GraphBuilder)

    request = ForwardPredictionRequest(
        sample_name="DP 0",
        inlet1=1.0,
        inlet2=0.0,
        chips=[
            {
                "position": position,
                "chip_type": f"{position}to{position}",
                "left_width_mm": 0.1 + position,
                "right_width_mm": 0.2 + position,
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
