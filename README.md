# Drug Gradient Chip App

This repository contains the application-side runtime wrapper for the trained
forward drug concentration gradient chip model.

Current scope:

- Structured forward prediction request schema.
- CSV adapter for the original forward prediction table.
- PyG graph construction from structured input.
- Runtime loading of the five `data_only` checkpoints.
- Ensemble prediction with per-seed values, mean, and population std.
- Golden sample test against the original model output.

Out of scope for this stage:

- Training.
- Modifying the original model repository.
- React frontend.
- FastAPI routes.
- Reverse model logic.
- Mock prediction results.

## Configuration

Set the original model project root with an environment variable:

```powershell
$env:MODEL_SOURCE_ROOT = "D:\pytorch_geometric-master"
$env:MODEL_DEVICE = "auto"
```

`MODEL_DEVICE` may be `auto`, `cpu`, or `cuda`.

## Runtime Usage

```python
from app.model_runtime.forward_adapter import ForwardModelAdapter
from app.schemas.forward import ForwardPredictionRequest

adapter = ForwardModelAdapter()
result = adapter.predict(
    ForwardPredictionRequest(
        sample_name="DP 0",
        inlet1=1.0,
        inlet2=0.0,
        chips=[...],
    )
)
```

The adapter loads model checkpoints once during initialization. Do not create a
new adapter for every prediction request.

## Tests

```powershell
pytest
```

If `MODEL_SOURCE_ROOT` is not configured, the real checkpoint golden test is
skipped. Unit tests that do not require real checkpoints still run.
