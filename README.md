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
conda activate drug-chip
$env:MODEL_SOURCE_ROOT = "D:\pytorch_geometric-master"
$env:FORWARD_MODEL_DEVICE = "cpu"
```

`FORWARD_MODEL_DEVICE` may be `cpu`, `cuda`, or `auto`. The default is `cpu`.
`MODEL_DEVICE` is still accepted only as a backward-compatible fallback.

The model assets remain in the external model repository. This project does not
copy or migrate checkpoints, and reverse prediction is not implemented yet.

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

## API

Start the API from the repository root:

```powershell
conda activate drug-chip
$env:MODEL_SOURCE_ROOT = "D:\pytorch_geometric-master"
$env:FORWARD_MODEL_DEVICE = "cpu"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Base URL:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Health check:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/health"
```

Model status:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/model-status"
```

Forward prediction:

```powershell
$body = @{
  sample_name = "DP 0"
  inlet1 = 1.0
  inlet2 = 0.0
  chips = @(
    @{
      position = 1
      chip_type = "5to4"
      left_width_mm = 0.261
      right_width_mm = 0.138
      left_bend_straight_distance_mm = 31
      right_bend_straight_distance_mm = 25
    },
    @{
      position = 2
      chip_type = "4to2"
      left_width_mm = 0.2
      right_width_mm = 0.1
      left_bend_straight_distance_mm = 30
      right_bend_straight_distance_mm = 24
    },
    @{
      position = 3
      chip_type = "1to6"
      left_width_mm = 0.2
      right_width_mm = 0.1
      left_bend_straight_distance_mm = 30
      right_bend_straight_distance_mm = 24
    },
    @{
      position = 4
      chip_type = "2to4"
      left_width_mm = 0.2
      right_width_mm = 0.1
      left_bend_straight_distance_mm = 30
      right_bend_straight_distance_mm = 24
    },
    @{
      position = 5
      chip_type = "6to3"
      left_width_mm = 0.2
      right_width_mm = 0.1
      left_bend_straight_distance_mm = 30
      right_bend_straight_distance_mm = 24
    },
    @{
      position = 6
      chip_type = "3to1"
      left_width_mm = 0.2
      right_width_mm = 0.1
      left_bend_straight_distance_mm = 30
      right_bend_straight_distance_mm = 24
    }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/forward" `
  -ContentType "application/json" `
  -Body $body
```
