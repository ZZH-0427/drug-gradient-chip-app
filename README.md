# 智能药物浓度预测平台

Windows application with a local FastAPI backend and React interface for
Forward Prediction, fixed-six-chip Reverse Prediction, and a Conversational
Predictor. The current Windows release candidate is `v0.3.0-rc9`.

## Current Product Scope

- Forward prediction uses `PhysicsGuidedDualTaskGNN` with one shared seed44
  checkpoint: fixed-six routing for 6 chips and dynamic zero-shot routing for
  4, 5, 7, 8, 9, and 10 chips.
- Forward prediction supports `chip_count=4` through `chip_count=10`.
- The checkpoint was trained on six-chip data. Runtime support for the other
  chip counts does not mean each scale was retrained or CFD validated.
- Forward public output contains concentration only.
- The model still computes flow internally, but flow is not exposed by the API
  or frontend.
- Reverse Prediction is available for fixed six-chip targets and runs through an
  asynchronous single-task API.
- Reverse results require independent Fluent/CFD validation before fabrication
  decisions.
- Conversational Predictor is implemented at `/assistant`. Its deterministic
  Chinese/English parser maintains a draft, requests confirmation, and then
  dispatches to the existing Forward adapter or Reverse task manager. It does
  not require a hosted language model or a remote prediction service.
- The interface supports Chinese and English. Chinese is the default language;
  the top-right language switcher persists the selection in browser
  `localStorage` with key `drug-gradient-chip.locale`.
- Language switching updates frontend text, `html lang`, and browser tab titles.
  The conversational API receives the selected locale in its `language` field
  for response text. API routes, engineering model inputs, checkpoints, and
  numeric predictions are unchanged by the locale selection.

## Windows rc9 Download and Installation

Use the Windows repository's [Releases](https://github.com/ZZH-0427/drug-gradient-chip-app/releases)
page and select [v0.3.0-rc9](https://github.com/ZZH-0427/drug-gradient-chip-app/releases/tag/v0.3.0-rc9).
As verified on 2026-11-12, this is a published **Pre-release**, with a Windows
x64 EXE installer and its `.sha256` file. It is a release candidate, not a
production-stable release. The rc9 Release does not currently attach a Portable
ZIP, although the portable build workflow exists.

1. Download the Windows x64 installer and checksum file from that rc9 page.
2. Verify the installer SHA256:
   `ed3a07f79c28d912879328d19e033c06ffe8f560890a8a1f3f974e3fa4d1cc4c`.
3. Run the installer, then launch the installed application from its Start menu
   or selected desktop shortcut. Browser Mode is an alternate Start menu entry.

The CPU package includes its Python runtime, application dependencies, built
frontend, and required checkpoint. End users do not need to install Python,
Conda, Node.js, or CUDA separately. Desktop mode uses WebView2; the Setup build
embeds its standalone installer. Inference runs locally after installation.

The rc9 tag points to source commit
`98f13e0f734a31959ab8da4cca288d8cb756bcf4`. Later Dataset and repository-maintenance
changes are not a rebuild of that existing EXE. No installer execution, new
build, or functional regression test was performed for this documentation update.

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

## Running from a Source Checkout

A Git clone is not the self-contained Windows package: the ignored checkpoint,
portable Python runtime, and built `frontend/dist` are not supplied by cloning.
`Dataset/` is research material, not a required input to application inference
or the installer payload, and does not replace the checkpoint.

Prepare a Python 3.11 environment with the declared PyTorch/PyTorch Geometric,
FastAPI, desktop, and other dependencies. The repository provides
`environment-py311.yml` and `requirements-py311-lock.txt`; CPU portable packaging
has its separate `environment-portable-cpu.yml`. Supply and verify the trusted
checkpoint as described above. Node.js/npm are needed when the production
frontend must be built; desktop mode also needs WebView2.

The lifecycle script uses a suitable packaged runtime or the configured Python
environment. Starting from source may build the frontend and write local
runtime state. The commands below document the workflow; they were not run as
part of this documentation update.

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

Conversational Predictor:

- `POST /api/v1/chat/message` parses Chinese/English engineering input and
  maintains a session draft.
- Execution is dispatched only after confirmation; Forward uses the existing
  adapter and Reverse uses the shared task manager and task polling API.

## Interface Language

Supported locales are `zh-CN` and `en`; invalid, empty, or unavailable stored
values fall back to Chinese. The product names are:

- Chinese: `正向预测`, `反向预测`, `智能预测助手` (`对话式预测`)
- English: `Forward Prediction`, `Reverse Prediction`, `Conversational Predictor`

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

Pass `-NoBrowser` as the first argument to use the background lifecycle path;
then open `http://127.0.0.1:8000` manually. This does not open the desktop shell.
Without that argument, packaged `start_app.cmd` defaults to the desktop window;
a source checkout without the packaged runtime uses the lifecycle script.

Static route ordering keeps `/api/v1/...` before SPA fallback. Unknown API paths
return JSON 404; `/`, `/forward`, `/reverse`, `/assistant`, and other non-API frontend paths
return the production frontend.

Lifecycle scripts identify the project Uvicorn process by PID, process start
time, executable path, app module, host, port, and `--app-dir`. Stop also cleans
reverse worker processes that match this project root.

## Windows Desktop Shell

Packaged Windows builds start in desktop-window mode through `launcher.pyw` and
`pywebview==6.2.1` using the Edge WebView2 renderer. The packaged `start_app.cmd`
launches the desktop shell, while `browser_app.cmd` keeps a Browser Mode fallback that opens
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

These commands are for an appropriately prepared development environment.
Historical release validation and the presence of test source do not mean a
new checkout has passed them; none were run for this documentation update.

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

Portable and Setup build workflows are implemented in
`scripts/build_portable_package.ps1`, `scripts/build_windows_installer.ps1`, and
`installer/windows/DrugGradientChip.iss`. They use the same
`model_assets/physics_gnn` assets and single-port lifecycle scripts. The package
scope is the shared seed44 checkpoint, application runtime files, built
frontend, and portable Python runtime; `.runtime`, worker logs, task outputs,
source model repositories, `Dataset/`, and old five-seed assets are outside
that delivery scope. See the rc9 Release above for attachments actually published.

No release ZIP is generated as part of ordinary development.
