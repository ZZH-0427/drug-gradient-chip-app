# Windows Development Status

Status reviewed on 2026-11-12 against the Windows rc9 application source and the
published `v0.3.0-rc9` Release. The release tag points to
`98f13e0f734a31959ab8da4cca288d8cb756bcf4`; later Dataset and repository-maintenance
commits do not establish a new build provenance for the existing installer.

## Implemented Application Scope

- **Forward Prediction:** 4 through 10 chips, one shared seed44
  `PhysicsGuidedDualTaskGNN` checkpoint. Six chips use the fixed-six route;
  4, 5, 7, 8, 9, and 10 use dynamic zero-shot routing. Public output is
  concentration-only; flow remains internal. Five-seed ensemble statistics are
  not part of the current public API or frontend.
- **Reverse Prediction:** exactly six target concentrations and explicit
  high-concentration inlet selection. The asynchronous single-task workflow
  supports creation, polling, and cancellation through `/api/v1/reverse-tasks`.
- **Conversational Predictor:** implemented at `/assistant`, with
  `POST /api/v1/chat/message`. A deterministic bilingual parser maintains a
  draft and requires confirmation before execution. Forward dispatches to the
  existing adapter; Reverse dispatches to the shared task manager and its
  worker lifecycle. This is not a hosted language-model integration.
- **Languages:** `zh-CN` and `en`, Chinese by default. The frontend persists the
  selection under `drug-gradient-chip.locale`; locale changes do not change
  model inputs, results, or API contracts.
- **Desktop and browser:** packaged builds default to a pywebview/WebView2
  window. Browser Mode opens the same local service in the system browser as a
  fallback. Start/stop/status scripts manage backend and Reverse-worker
  lifecycle; they are current components, not obsolete launchers.
- **Local inference:** FastAPI serves the production frontend and API on
  `127.0.0.1:8000`, including `/`, `/forward`, `/reverse`, and `/assistant`.
  Prediction needs no remote inference service. Development dependency
  downloads and initial environment preparation are separate requirements.

## Windows Delivery and Source Requirements

As verified on 2026-11-12, [Windows rc9](https://github.com/ZZH-0427/drug-gradient-chip-app/releases/tag/v0.3.0-rc9)
is a published Pre-release with a Windows x64 EXE installer and checksum file.
The installer SHA256 is
`ed3a07f79c28d912879328d19e033c06ffe8f560890a8a1f3f974e3fa4d1cc4c`.
No rc9 Portable ZIP is currently attached. Portable and Setup build scripts
already exist; their existence is distinct from which artifacts are published.

The CPU distribution bundles Python, application dependencies, the production
frontend, and required model assets. End users need not separately install
Python, Conda, Node.js, or CUDA. Setup embeds the WebView2 standalone installer.
Portable desktop mode requires an available WebView2 Runtime; Browser Mode is
the alternative when that runtime is unavailable.

A source checkout has different prerequisites: the Git-ignored checkpoint,
Python/PyTorch/PyG and desktop dependencies, and Node/npm when the frontend
needs building. The manifest remains tracked in `model_assets/physics_gnn/`.
`Dataset/` is not a required application inference input or installer payload.

Use the [README](../README.md) for model provisioning, environment declarations,
and run commands. With `-NoBrowser` as its first argument, `start_app.cmd` takes
the background lifecycle path; open `http://127.0.0.1:8000` manually. This is not
a desktop-window launch. A source checkout without the packaged runtime also
uses the lifecycle script.

## Verification Boundary and Known Limits

The features above are supported by current source references. Prior build,
installation, and regression results belong to historical release validation;
this documentation update did not run the installer, application, models,
tests, builds, or environment installation. The current checkout is not claimed
to have newly passed them. Prepared environments may use the commands in
[Development Checks](../README.md#development-checks); these are instructions,
not results of this maintenance task.

- Non-six Forward scales use six-chip-trained weights; runtime support does
  not establish independent scientific validation for every scale.
- Reverse is fixed to six chips, may take tens of seconds on CPU, and returns
  a surrogate-model design requiring independent Fluent/CFD validation before
  fabrication decisions.
- Unit tests alone do not establish installed desktop/browser interaction or
  device-specific compatibility. Relevant manual smoke checks remain distinct.

## Runtime Contracts and Verification

- **Checkpoint compatibility:** the Forward loader checks the
  `PhysicsGuidedDualTaskGNN` model type, required `model_state_dict` and
  normalizers, and supported feature dimensions. Architecture metadata and
  implemented defaults determine model construction; `load_state_dict` uses
  `strict=True`. Packaged asset identity and routing metadata are checked
  separately by `scripts/verify_forward_assets.ps1` against the model manifest.
- **Input representation:** feature order, chip-category encoding, graph
  construction, and normalization in the graph builders must be compatible
  with the checkpoint. CSV/table parsing produces validated
  `ForwardPredictionRequest` objects; it is an input adapter, not an alternative
  model contract.
- **Loading lifecycle:** with model loading enabled, backend startup creates
  and retains the Forward adapter for request handling. Reverse optimization
  runs in a separate worker process and loads its model there; it does not
  share the backend's already-loaded Forward model instance.
- **Verification coverage:** schema, graph/routing, Forward Golden comparisons,
  and Reverse/Chat API and session checks are covered by test source under
  `backend/tests/`. Frontend checks and installed desktop/browser smoke checks
  are separate verification scopes; see [Development Checks](../README.md#development-checks).
- **Prerequisites and results:** real-model numerical checks require a
  compatible checkpoint and model dependencies. Some source-parity checks also
  require an external reference script and can be skipped if it is absent.
  Verification reports should distinguish passed, failed, skipped, and unrun
  checks. Mocked or schema-only checks do not replace real-checkpoint numerical
  comparisons; test results alone do not establish installation compatibility
  or independent Fluent/CFD validation.
