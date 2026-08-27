from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from app.core.errors import ModelRuntimeError
from app.model_runtime.reverse_optimizer import ReverseOptimizationParameters, run_reverse_design


TARGET_ONLY_INLET_RELATIONS = ((1.0, 0.0), (0.0, 1.0))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def reverse_request_variants(request: dict[str, Any]) -> list[tuple[float, float, list[float]]]:
    if "target_concentrations" not in request:
        raise ValueError("Reverse request must include target_concentrations.")
    targets = [float(item) for item in request["target_concentrations"]]
    if len(targets) != 6:
        raise ValueError("Reverse request requires exactly six target concentrations.")
    has_inlet1 = "inlet1" in request
    has_inlet2 = "inlet2" in request
    if has_inlet1 != has_inlet2:
        raise ValueError("Reverse request must include both inlet1 and inlet2 or neither.")
    if has_inlet1 and has_inlet2:
        return [(float(request["inlet1"]), float(request["inlet2"]), targets)]
    return [(inlet1, inlet2, list(targets)) for inlet1, inlet2 in TARGET_ONLY_INLET_RELATIONS]


def finite_metric(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def reverse_result_rank(result: dict[str, Any]) -> tuple[int, float, float, float, float]:
    metrics = result.get("metrics", {})
    return (
        0 if bool(metrics.get("internal_screening_pass")) else 1,
        finite_metric(metrics.get("mae"), default=float("inf")),
        finite_metric(metrics.get("rmse"), default=float("inf")),
        finite_metric(metrics.get("maxae"), default=float("inf")),
        -finite_metric(metrics.get("spearman"), default=float("-inf")),
    )


def run_reverse_request(
    request: dict[str, Any],
    *,
    device: str,
    checkpoint_path: Path,
) -> dict[str, Any]:
    results = [
        run_reverse_design(
            inlet1=inlet1,
            inlet2=inlet2,
            target_concentrations=target_concentrations,
            device=device,
            checkpoint_path=checkpoint_path,
            parameters=ReverseOptimizationParameters(),
        )
        for inlet1, inlet2, target_concentrations in reverse_request_variants(request)
    ]
    return min(results, key=reverse_result_rank)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-json", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--application-root", type=Path, required=True)
    args = parser.parse_args()

    try:
        request = json.loads(args.request_json.read_text(encoding="utf-8"))
        result = run_reverse_request(
            request,
            device=args.device,
            checkpoint_path=args.checkpoint,
        )
        write_json(args.result_json, {"ok": True, "result": result})
    except ModelRuntimeError as exc:
        write_json(args.result_json, {"ok": False, "error": exc.to_dict()})
        raise SystemExit(1)
    except Exception as exc:
        write_json(
            args.result_json,
            {
                "ok": False,
                "error": {
                    "code": "REVERSE_TASK_FAILED",
                    "message": "Reverse design task failed.",
                    "details": {"error": type(exc).__name__},
                },
            },
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
