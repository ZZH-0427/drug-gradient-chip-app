# Development Status

## Completed

- Forward model runtime structure created.
- Forward request and response schemas added.
- CSV adapter added for the original forward prediction table.
- Graph builder added with centralized template dataset access.
- `DataOnlyGNNTransformer` runtime model class added.
- Five-seed checkpoint loader added.
- Ensemble inference and output mapping added.
- FastAPI health, model-status, and forward routes added.
- Bundled forward model asset layout added under `model_assets/forward`.
- Copy and verification scripts added for local forward assets.
- Golden CSV fixtures moved under `backend/tests/fixtures/forward`.
- Forward prediction frontend MVP added under `frontend/`.
- Single-port local delivery mode added through FastAPI static frontend serving.
- Local start, stop, and status scripts added.
- The inverse workflow has been formally removed from the product scope.
- Dynamic chip-count request and frontend form structure added for 4 to 10 chips.

## Current Run Mode

Default bundled mode:

```powershell
Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue
$env:FORWARD_MODEL_DEVICE = "cpu"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

External compatibility mode remains available by setting `MODEL_SOURCE_ROOT` to
an old-layout model source directory.

Frontend development mode:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

Local delivery mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_app.ps1
```

This serves the production frontend and API together from:

```text
http://127.0.0.1:8000
```

## Test Command

```powershell
python -m pytest -q
```

Latest backend result before the dynamic chip-count transition:

```text
35 passed, 1 skipped
```

The bundled golden test runs when local `.pt` assets are provisioned. External
compatibility tests run when `MODEL_SOURCE_ROOT` is set.

Frontend checks:

```powershell
cd frontend
npm run typecheck
npm run lint
npm run test:run
npm run build
```

Latest frontend result before the dynamic chip-count transition:

```text
15 passed
typecheck passed
lint passed
build passed
```

## Golden Sample

The golden test reads fixture CSV files from:

- `backend/tests/fixtures/forward/forward_prediction_input.csv`
- `backend/tests/fixtures/forward/forward_prediction_expected.csv`

It compares all six means, all six std values, and all five seed outputs with a
maximum absolute tolerance of `1e-6`.

## Known Limits

- Runtime `.pt` assets are local files ignored by Git and must be provisioned.
- The current forward model supports real inference for exactly 6 chips.
- The transition UI can configure 4 to 10 chips, but non-six counts cannot run
  prediction until the variable-node model is delivered.
- The inverse workflow is cancelled and is no longer listed as a future task.
- Browser interaction is not covered by the unit test suite.
- Windows EXE/installers, services, Docker, and cloud deployment are not
  implemented.

## Next Steps

- Decide the long-term distribution mechanism for model assets, such as a
  controlled artifact store or release process.
- Integrate the future variable-node forward model for real 4 to 10 chip
  inference when that model is delivered.
