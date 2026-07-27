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
        result = run_reverse_design(
            inlet1=float(request["inlet1"]),
            inlet2=float(request["inlet2"]),
            target_concentrations=[float(item) for item in request["target_concentrations"]],
            device=args.device,
            checkpoint_path=args.checkpoint,
            parameters=ReverseOptimizationParameters(),
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
