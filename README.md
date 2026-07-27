# Drug Gradient Chip App

Local FastAPI and React application for drug concentration gradient chip
prediction and fixed-six-chip reverse design.

## Current Product Scope

- Forward prediction uses the official fixed-six `PhysicsGuidedDualTaskGNN`
  checkpoint.
- Forward public output contains concentration only.
- The model still computes flow internally, but flow is not exposed by the API
  or frontend.
- The frontend can configure 4 through 8 chips as a transition UI, but only
  `chip_count=6` can run real prediction.
- Non-six forward requests return `UNSUPPORTED_CHIP_COUNT` before the model
  adapter is called.
- Reverse design is restored for fixed six-chip targets and runs through an
  asynchronous single-task API.
- Reverse results require independent Fluent/CFD validation before fabrication
  decisions.

The current official forward model does not support real 4 through 8 variable
chip inference. That support must wait for an updated official `forward_predict`
implementation.

## Model Assets

Bundled assets live under:

```text
model_assets/physics_gnn/
  best_concentration_checkpoint.pt
  manifest.json
```

The checkpoint binary is ignored by Git. The manifest records safe metadata:
model family, checkpoint file name, SHA-256, size, supported forward/reverse
chip counts, and public output type.

Copy assets from a trusted model source:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\copy_forward_assets.ps1 `
  -SourceRoot <model-source-root>
```

Verify bundled assets:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_forward_assets.ps1 `
  -PythonPath <python.exe>
```

`MODEL_SOURCE_ROOT` remains available only for external compatibility. If it is
unset, empty, or whitespace-only, the app uses bundled assets. If it is set to a
non-empty path, the app strictly uses the external old layout and does not fall
back to bundled assets on failure.

Recommended runtime device variable:

```powershell
$env:FORWARD_MODEL_DEVICE = "cpu"
```

`MODEL_DEVICE` is accepted only as a backward-compatible fallback when
`FORWARD_MODEL_DEVICE` is not set.

## API

Health and status:

- `GET /api/v1/health`
- `GET /api/v1/model-status`

Forward:

- `POST /api/v1/forward`
- Request contains `sample_name`, optional `chip_count`, `inlet1`, `inlet2`,
  and chip rows.
- Forward chip `left_width_mm` and `right_width_mm` must be finite values from
  `0.04` through `0.31` mm. The frontend width inputs use `step=0.001`; bend
  straight distance inputs keep `step=1`.
- Response contains `chip_count` and six concentration predictions.
- The response does not contain `flow`, `mean`, `std`, `seed_values`, or
  checkpoint paths.

Reverse:

- `POST /api/v1/reverse-tasks` returns `202` and `task_id`.
- `GET /api/v1/reverse-tasks/{task_id}` polls task state and result.
- `DELETE /api/v1/reverse-tasks/{task_id}` cancels queued/running tasks.
- At most one reverse task runs at a time.
- Task state, worker logs, and outputs stay under `.runtime/` and are ignored by
  Git.

## Local Single-Port Run

Builds the production frontend only when needed, verifies bundled model assets,
starts FastAPI on port 8000, and serves the SPA and API from one process:

```powershell
.\start_app.cmd -NoBrowser
.\status_app.cmd
.\stop_app.cmd
```

Static route ordering keeps `/api/v1/...` before SPA fallback. Unknown API paths
return JSON 404; `/`, `/forward`, `/reverse`, and other non-API frontend paths
return the production frontend.

Lifecycle scripts identify the project Uvicorn process by PID, process start
time, executable path, app module, host, port, and `--app-dir`. Stop also cleans
reverse worker processes that match this project root.

## Development Checks

Backend:

```powershell
python -m compileall backend
python -m pytest -q --basetemp=.pytest_tmp
python -m pip check
```

Frontend:

```powershell
cd frontend
npm run typecheck
npm run lint
npm run test:run
npm run build
cd ..
```

Asset verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_forward_assets.ps1 `
  -PythonPath <python.exe>
```

## Portable Build Logic

Portable packaging uses the same `model_assets/physics_gnn` assets and the same
single-port lifecycle scripts. The future package should include only the shared
seed44 checkpoint, application runtime files, built frontend, and portable
Python runtime. It must not include `.runtime`, worker logs, task outputs,
source model repositories, datasets, or old five-seed assets.

No release ZIP is generated as part of ordinary development.
