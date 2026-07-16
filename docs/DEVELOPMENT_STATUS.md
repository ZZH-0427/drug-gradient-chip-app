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

## Current Run Mode

Default bundled mode:

```powershell
Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue
$env:FORWARD_MODEL_DEVICE = "cpu"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

External compatibility mode remains available by setting `MODEL_SOURCE_ROOT` to
an old-layout model source directory.

## Test Command

```powershell
python -m pytest -q
```

The bundled golden test runs when local `.pt` assets are provisioned. External
compatibility tests run when `MODEL_SOURCE_ROOT` is set.

## Golden Sample

The golden test reads fixture CSV files from:

- `backend/tests/fixtures/forward/forward_prediction_input.csv`
- `backend/tests/fixtures/forward/forward_prediction_expected.csv`

It compares all six means, all six std values, and all five seed outputs with a
maximum absolute tolerance of `1e-6`.

## Known Limits

- Runtime `.pt` assets are local files ignored by Git and must be provisioned.
- No frontend exists in this stage.
- No reverse model logic exists in this stage.

## Next Steps

- Decide the long-term distribution mechanism for model assets, such as a
  controlled artifact store or release process.
