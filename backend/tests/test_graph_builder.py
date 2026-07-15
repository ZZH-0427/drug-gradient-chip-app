from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from app.model_runtime.graph_builder import GraphBuilder
from app.schemas.forward import ForwardPredictionRequest


def test_graph_builder_generates_expected_raw_tensors() -> None:
    builder = GraphBuilder.__new__(GraphBuilder)
    builder.edge_index = torch.tensor(
        [[0, 1, 1, 2, 2, 3, 3, 4, 4, 5], [1, 0, 2, 1, 3, 2, 4, 3, 5, 4]],
        dtype=torch.long,
    )
    builder.edge_attr = torch.zeros((10, 2), dtype=torch.float32)

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

    assert tuple(graph.x.shape) == (6, 7)
    assert tuple(graph.edge_index.shape) == (2, 10)
    assert tuple(graph.edge_attr.shape) == (10, 2)
    assert tuple(graph.u.shape) == (1, 2)
    assert graph.x[:, 4].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert graph.x[:, 5].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert graph.x[:, 6].tolist() == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert graph.u.tolist() == [[1.0, 0.0]]
