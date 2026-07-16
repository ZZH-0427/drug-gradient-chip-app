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
- FastAPI routes for health, model status, and forward prediction.
- React/Vite frontend MVP for the forward prediction workflow.

Out of scope for this stage:

- Training.
- Modifying the original model repository.
- Reverse model logic.
- Mock prediction results.

## Model Assets

The API defaults to local bundled forward model assets under:

```text
model_assets/forward
```

The `.pt` files in that directory are runtime assets and are ignored by Git. A
fresh clone must provision them before running the real model.

Provision the local assets from a read-only source model directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\copy_forward_assets.ps1 `
  -SourceRoot "D:\pytorch_geometric-master"
```

Verify the local copies against `model_assets/forward/manifest.json`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_forward_assets.ps1
```

`manifest.json` records expected file sizes and SHA-256 hashes. It does not
contain source paths or machine-specific data.

## Configuration

Default bundled startup does not require `MODEL_SOURCE_ROOT`:

```powershell
conda activate drug-chip
Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue
$env:FORWARD_MODEL_DEVICE = "cpu"
```

`FORWARD_MODEL_DEVICE` may be `cpu`, `cuda`, or `auto`. The default is `cpu`.
`MODEL_DEVICE` is still accepted only as a backward-compatible fallback.

`MODEL_SOURCE_ROOT` is now optional. If it is set to a non-empty value, the
runtime strictly uses the old external model repository layout and does not fall
back to bundled assets when the path is invalid.

The backend CORS allow-list is configured by `FRONTEND_ORIGINS`. The default
allows local Vite development:

```powershell
$env:FRONTEND_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
```

The frontend reads `VITE_API_BASE_URL`; the default development value is:

```text
http://127.0.0.1:8000
```

Reverse prediction is not implemented yet.

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

If local `.pt` assets are present, bundled real-model tests run without
`MODEL_SOURCE_ROOT`. External compatibility tests run when `MODEL_SOURCE_ROOT` is
set.

## API

Start the API from the repository root:

```powershell
conda activate drug-chip
Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue
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

## Frontend

Install frontend dependencies from the frontend project only:

```powershell
cd frontend
npm install
```

Start Vite:

```powershell
npm run dev -- --host 127.0.0.1
```

Frontend URL:

```text
http://127.0.0.1:5173
```

The forward page checks `/api/v1/model-status`, validates six fixed chip
positions, confirms parameters, and calls `/api/v1/forward`. The reverse page is
a placeholder because the reverse model is not integrated.

Frontend verification commands:

```powershell
cd frontend
npm run typecheck
npm run lint
npm run test:run
npm run build
```

Use `npm ci` for clean lockfile-based validation after `package-lock.json` has
been generated.
