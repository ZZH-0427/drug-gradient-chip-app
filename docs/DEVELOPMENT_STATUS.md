# Development Status

## Completed

- Project runtime structure created.
- Forward request and response schemas added.
- CSV adapter added for the original forward prediction table.
- Graph builder added with centralized template dataset access.
- `DataOnlyGNNTransformer` runtime model class added.
- Five-seed checkpoint loader added.
- Ensemble inference and output mapping added.
- Unit tests and golden sample test added.
- Project docs and configuration examples added.

## Current Run Mode

Configure:

```powershell
$env:MODEL_SOURCE_ROOT = "D:\pytorch_geometric-master"
$env:MODEL_DEVICE = "auto"
```

Then initialize `ForwardModelAdapter` once and call `predict(request)`.

## Test Command

```powershell
pytest
```

The golden test is skipped when `MODEL_SOURCE_ROOT` is not configured.

## Golden Sample

The golden test reads:

- `正向预测与反向预测/正向预测/正向预测输入/正向预测.csv`
- `正向预测与反向预测/正向预测/正向预测结果/forward_prediction_results.csv`

It compares all six means, all six std values, and all five seed outputs with a
maximum absolute tolerance of `1e-6`.

## Known Limits

- Runtime dependencies must be installed by the environment owner.
- The graph template still depends on `physics_gnn_dataset.pt`.
- No frontend or API route exists in this stage.
- No reverse model logic exists in this stage.

## Next Steps

- Run validation in the target Python environment.
- If deployment should avoid carrying `physics_gnn_dataset.pt`, formally freeze
  and audit the template edge data in application-owned configuration.
