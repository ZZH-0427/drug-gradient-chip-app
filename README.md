# Drug Gradient Chip App

Local FastAPI and React application for drug concentration gradient chip
dynamic forward prediction and fixed-six-chip Reverse Prediction.

## Current Product Scope

- Forward prediction uses the official dynamic `PhysicsGuidedDualTaskGNN`
  runtime with one shared seed44 checkpoint.
- Forward prediction supports `chip_count=4` through `chip_count=10`.
- The checkpoint was trained on six-chip data and is used for zero-shot scale
  extension to 4 through 10 chips; runtime support does not mean each scale was
  retrained or CFD validated.
- Forward public output contains concentration only.
- The model still computes flow internally, but flow is not exposed by the API
  or frontend.
- Reverse Prediction is available for fixed six-chip targets and runs through an
  asynchronous single-task API.
- Reverse results require independent Fluent/CFD validation before fabrication
  decisions.
- The interface supports Chinese and English. Chinese is the default language;
  the top-right language switcher persists the selection in browser
  `localStorage` with key `drug-gradient-chip.locale`.
- Language switching affects only frontend text, `html lang`, and browser tab
  titles. API routes, request payloads, model checkpoints, and model results are
  unchanged.

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
- Response contains `chip_count` and one concentration prediction per chip.
- The response does not contain `flow`, `mean`, `std`, `seed_values`, or
  checkpoint paths.

Reverse:

- `POST /api/v1/reverse-tasks` returns `202` and `task_id`.
- `GET /api/v1/reverse-tasks/{task_id}` polls task state and result.
- `DELETE /api/v1/reverse-tasks/{task_id}` cancels queued/running tasks.
- At most one reverse task runs at a time.
- Task state, worker logs, and outputs stay under `.runtime/` and are ignored by
  Git.

## Interface Language

Supported locales are `zh-CN` and `en`; invalid, empty, or unavailable stored
values fall back to Chinese. The product names are:

- Chinese: `正向预测`, `反向预测`
- English: `Forward Prediction`, `Reverse Prediction`

Forward Prediction supports four to ten chips. Reverse Prediction remains fixed
to 6 chips and still requires independent Fluent/CFD validation.

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

## Windows Desktop Shell

Packaged Windows builds start in desktop-window mode through `launcher.pyw` and
`pywebview==6.2.1` using the Edge WebView2 renderer. `start_app.cmd` launches the
desktop shell, while `browser_app.cmd` keeps a Browser Mode fallback that opens
the same local single-port app in the system browser.

Setup builds embed the official Microsoft Edge WebView2 x64 Evergreen Standalone
Installer from `WEBVIEW2_INSTALLER_PATH`. The build script verifies that input is
a Microsoft-signed x64 standalone installer and records its size, SHA-256, and
file version in package metadata. Portable ZIP builds do not embed WebView2; if
the target machine lacks WebView2 Runtime, desktop mode reports the issue and
Browser Mode remains available.

The desktop shell keeps the backend lifecycle in the existing scripts, starts
subprocesses without visible console windows, restricts the main window to
`http://127.0.0.1:8000`, opens external links in the system browser, uses a
loopback single-instance activation socket, and asks for confirmation before
closing while a reverse task is running.

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
