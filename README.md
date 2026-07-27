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
- Mock prediction results.
- The inverse workflow is outside the product scope.

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

The application provides forward prediction only. The inverse workflow is not
part of the product scope.

## Runtime Usage

```python
from app.model_runtime.forward_adapter import ForwardModelAdapter
from app.schemas.forward import ForwardPredictionRequest

adapter = ForwardModelAdapter()
result = adapter.predict(
    ForwardPredictionRequest(
        sample_name="DP 0",
        chip_count=6,
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
python -m uvicorn backend.app.main:app --app-dir . --host 127.0.0.1 --port 8000
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
  chip_count = 6
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

The forward page checks `/api/v1/model-status`, lets users select 4 to 10 chips,
generates one position and two point labels for each chip, validates parameters,
confirms parameters, and calls `/api/v1/forward` only when `chip_count=6`.

This is a transition version. The current bundled model still supports real
inference for exactly six chips. Non-six chip counts can be configured and
confirmed in the UI, but prediction is blocked until the future variable-node
model is integrated. The default chip count is 6.

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

## Local Delivery Mode

For normal local use, run the single-port application from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_app.ps1
```

Or double-click:

```text
start_app.cmd
```

Then open:

```text
http://127.0.0.1:8000
```

The start script checks the repository layout, verifies bundled forward model
assets, locates the `drug-chip` Conda Python, builds `frontend/dist` only when
needed, starts one Uvicorn/FastAPI process with `--app-dir`, writes `.runtime/app-state.json`,
and stores logs under `.runtime/logs/`.

Useful commands:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\status_local_app.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\stop_local_app.ps1
```

Double-click wrappers are also available:

```text
status_app.cmd
stop_app.cmd
```

Common start options:

```powershell
.\scripts\start_local_app.ps1 -Port 8010
.\scripts\start_local_app.ps1 -Device cpu
.\scripts\start_local_app.ps1 -RebuildFrontend
.\scripts\start_local_app.ps1 -NoBrowser
.\scripts\start_local_app.ps1 -Foreground
```

In local delivery mode, FastAPI serves both `/api/v1/...` and the production
frontend from `frontend/dist`. The app does not require Vite or port 5173 at
runtime. `frontend/dist`, `.runtime`, logs, PID state, `.pt` files, and
`node_modules` are local artifacts and are not committed.

Troubleshooting:

- If port 8000 is occupied, the start script reports the owning PID and process
  name. It does not stop unrelated processes.
- If model assets are missing or hashes do not match, rerun
  `scripts/copy_forward_assets.ps1` from a trusted source and verify again.
- If `drug-chip` cannot be found, create it from `environment-py311.yml` or pass
  `-PythonPath` to a valid environment Python.
- If frontend build fails, inspect npm output and rerun with `-RebuildFrontend`.
- If status reports `stale`, run `status_local_app.ps1 -CleanStale` to clear
  invalid state. `stop_local_app.ps1` only stops a process whose PID, start
  time, Python executable, app module, host, port, and `--app-dir` match the
  state file, so unrelated Uvicorn processes are not stopped.

## Windows Portable Package

Build a self-contained Windows x64 package from a clean Git working tree:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable_package.ps1
```

Build the CPU-only distribution from the isolated CPU runtime environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_portable_package.ps1 `
  -RuntimeCondaEnvironment drug-chip-portable-cpu `
  -DistributionFlavor CPU
```

The build script uses `conda-pack` only from the separate local build-tool
environment `drug-chip-portable-build`. It does not install `conda-pack` into
`drug-chip`, does not modify application dependencies, and does not include the
build-tool environment in the package.

The CPU runtime environment is defined in `environment-portable-cpu.yml`. It uses
the official PyTorch CPU wheel and PyG CPU wheels; `torch.version.cuda` is
`None`, `torch.cuda.is_available()` is `False`, and the CPU package audit checks
that CUDA runtime DLLs such as `torch_cuda.dll`, `cublas*.dll`, `cudnn*.dll`,
`cusparse*.dll`, `cufft*.dll`, and `cusolver*.dll` are absent.

Default output:

```text
release/DrugGradientChip-<version>-Windows-x64.zip
release/DrugGradientChip-<version>-Windows-x64.zip.sha256
```

CPU output:

```text
release/DrugGradientChip-<version>-Windows-x64-CPU.zip
release/DrugGradientChip-<version>-Windows-x64-CPU.zip.sha256
```

The ZIP contains:

- `runtime/` packed from the existing `drug-chip` Conda environment.
- `backend/app/`, lifecycle scripts, and `.cmd` wrappers.
- `frontend/dist/` production assets.
- `model_assets/forward/` including the bundled model binaries.
- `BUILD_INFO.json`, `VERSION`, `README.txt`, and `runtime-packages.txt`.

Release archives are written with ZIP64 and `ZIP_DEFLATED` compression. The
archive audit rejects generated runtime state, logs, PID files, Python bytecode,
Git metadata, frontend source files, backend tests, and development-machine path
fragments. Build size diagnostics are written under `.build/reports/`.

On an end-user Windows machine, extract the ZIP and run:

```text
start_app.cmd
status_app.cmd
stop_app.cmd
```

The portable package does not require Conda, Python, Node.js, npm, Vite, or the
original model repository. Portable startup detects `runtime/python.exe` and
`BUILD_INFO.json`, uses CPU by default, serves the bundled `frontend/dist`, and
forces bundled model assets for the child Uvicorn process even if
`MODEL_SOURCE_ROOT` exists in the parent shell.

On first start after extraction, the portable launcher runs the bundled
`runtime\Scripts\conda-unpack.exe` once in that final directory and writes
`runtime\.conda-unpacked`. Do not move a directory after it has been started. To
migrate the application, extract the original ZIP again at the target location.

The build script validates the package by starting it without Vite, checking
`/`, `/forward`, the `/reverse` Not Found route, `/api/v1/health`,
`/api/v1/model-status`, and a real `/api/v1/forward` request. It validates fresh ZIP extractions in a normal path
and a path containing spaces and non-ASCII characters, then verifies that moving
an already initialized directory is rejected. If `conda-pack` relocation fails,
do not replace it with a raw Conda environment copy; keep the diagnostics and
investigate the relocation failure.

Prediction parity between the CUDA development environment running on CPU and
the CPU-only runtime can be checked with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\compare_runtime_predictions.ps1
```

This compares three payloads across all ensemble seeds, prediction means, and
population standard deviations with a default tolerance of `1e-6`. A truly clean
Windows machine test without system Python, Conda, or Node.js still requires
separate manual execution on such a machine.

## Development Mode

Development mode remains split across two services:

```powershell
python -m uvicorn backend.app.main:app --app-dir . --host 127.0.0.1 --port 8000
cd frontend
npm run dev -- --host 127.0.0.1
```

In development, the frontend defaults to `http://127.0.0.1:8000` for API calls.
In production builds without `VITE_API_BASE_URL`, API calls use same-origin
relative paths such as `/api/v1/forward`. Use `FRONTEND_ORIGINS` only for the
split development server flow.
