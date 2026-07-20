# Model Runtime Design

## Application Schema

The application accepts `ForwardPredictionRequest`: one sample name, an optional
`chip_count`, two inlet values, and chip entries. During the transition version,
`chip_count` may be 4 through 10 and defaults to 6 for old requests. The chip
entry count must equal `chip_count`; positions must be consecutive from 1 through
`chip_count` without duplicates. All numeric values must be finite.

The current forward model can run real inference only when `chip_count=6`.

## CSV Adapter

`input_parser.py` reads the original forward prediction CSV and converts it into
the structured request schema. The model runtime does not depend on CSV columns.

## Graph Builder

`GraphBuilder` builds:

- `x`: `[6, 7]`
- `edge_index`: `[2, 10]`
- `edge_attr`: `[10, 2]`
- `u`: `[1, 2]`

It reads `physics_gnn_dataset.pt` in one centralized place to obtain and verify
the template graph.

## Model Loading

`ForwardModelLoader` loads five `data_only` checkpoints from `MODEL_SOURCE_ROOT`.
It validates `ablation_variant`, `model_state_dict`, `architecture`, and required
normalizers. State dict loading uses `strict=True`, and each model is placed in
`eval()` mode.

## Standardization

Each seed uses its own checkpoint normalizers:

- `x_mean`, `x_std`
- `edge_mean`, `edge_std`
- `u_mean`, `u_std`

No output inverse transform, clipping, Normalized, Offset, DP 0 difference, or
teshu reversal is applied.

## Ensemble

`ForwardEnsemble` runs each seed under `torch.inference_mode()`, stacks outputs,
and computes:

- `mean(axis=0)`
- `std(axis=0, ddof=0)`

## Output Mapping

`result_mapper.py` converts NumPy values into plain Python floats. With the
current fixed model it returns six ordered predictions: `y1` through `y6`.

## Errors

Runtime errors use structured codes:

- `MODEL_SOURCE_ROOT_MISSING`
- `MODEL_ASSET_NOT_FOUND`
- `MODEL_CHECKPOINT_INVALID`
- `MODEL_INPUT_SCHEMA_ERROR`
- `MODEL_INFERENCE_FAILED`
- `MODEL_OUTPUT_SCHEMA_ERROR`

Upper layers should return these codes without exposing full Python stack traces.

## FastAPI Use

The application creates one `ForwardModelAdapter` during startup and reuses it
for requests. Route handlers validate HTTP payloads, reject non-six chip counts
before calling the adapter, call `adapter.predict(request)` only for supported
six-chip requests, and map structured errors to HTTP responses.
