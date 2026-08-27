from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.errors import ModelRuntimeError
from app.model_runtime.reverse_optimizer import ReverseOptimizationParameters, run_reverse_design


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def reverse_request_values(request: dict[str, Any]) -> tuple[float, float, list[float]]:
    if "inlet1" not in request or "inlet2" not in request:
        raise ValueError("Reverse request must include inlet1 and inlet2.")
    if "target_concentrations" not in request:
        raise ValueError("Reverse request must include target_concentrations.")
    targets = [float(item) for item in request["target_concentrations"]]
    if len(targets) != 6:
        raise ValueError("Reverse request requires exactly six target concentrations.")
    return float(request["inlet1"]), float(request["inlet2"]), targets


def run_reverse_request(
    request: dict[str, Any],
    *,
    device: str,
    checkpoint_path: Path,
) -> dict[str, Any]:
    inlet1, inlet2, target_concentrations = reverse_request_values(request)
    return run_reverse_design(
        inlet1=inlet1,
        inlet2=inlet2,
        target_concentrations=target_concentrations,
        device=device,
        checkpoint_path=checkpoint_path,
        parameters=ReverseOptimizationParameters(),
    )


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
