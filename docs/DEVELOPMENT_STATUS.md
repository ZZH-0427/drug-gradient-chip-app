# Development Status

## Completed

- Official dynamic `PhysicsGuidedDualTaskGNN` forward runtime is integrated.
- Bundled model assets use `model_assets/physics_gnn/` with one seed44
  checkpoint and a safe manifest.
- Forward public output is concentration-only; flow remains internal.
- Five-seed ensemble fields, mean/std, and seed values are removed from the
  public API and frontend.
- Forward Prediction supports 4 through 10 chips with zero-shot scale extension
  from the six-chip training checkpoint.
- Fixed-six Reverse Prediction is available as an asynchronous single-task
  workflow.
- The frontend supports `zh-CN` and `en`; Chinese is the default and the
  selected locale is stored under `drug-gradient-chip.locale`.
- Local single-port delivery serves `/`, `/forward`, `/reverse`, and API routes
  from port 8000 without Vite.

## Current Run Mode

Default bundled mode:

```powershell
Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue
$env:FORWARD_MODEL_DEVICE = "cpu"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

External compatibility remains available by setting `MODEL_SOURCE_ROOT` to a
valid old-layout model source directory. Empty or whitespace-only
`MODEL_SOURCE_ROOT` uses bundled assets.

Local delivery mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_app.ps1 -NoBrowser
```

## Test Commands

```powershell
python -m compileall backend
python -m pytest -q --basetemp=.pytest_tmp
python -m pip check
powershell -ExecutionPolicy Bypass -File .\scripts\verify_forward_assets.ps1 -PythonPath <python.exe>
```

```powershell
cd frontend
npm run typecheck
npm run lint
npm run test:run
npm run build
```

## Known Limits

- Forward Prediction uses six-chip trained weights for zero-shot 4 through 10
  scale extension; each non-six scale still requires independent scientific
  validation before fabrication decisions.
- Reverse Prediction is fixed to 6 chips, may take tens of seconds on CPU, and
  returns a surrogate-model design that still requires independent Fluent/CFD
  validation.
- Browser interaction is not covered by the automated unit suite.

## Next Steps

- Keep dynamic forward tests covering 4 through 10 chip counts as the product
  evolves.
- Keep release packages limited to the shared seed44 checkpoint and application
  runtime files.
