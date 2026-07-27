# Model Runtime Design

## Application Schema

The forward API accepts `chip_count` from 4 through 8 and defaults missing
`chip_count` to 6 for old clients. The current official forward model still runs
real inference only for exactly 6 chips; 4, 5, 7, and 8 are rejected before the
adapter is called.

## Forward Runtime

The application uses the official fixed-six `PhysicsGuidedDualTaskGNN` runtime
with one bundled checkpoint under `model_assets/physics_gnn/`. The public
forward response contains only six concentration values. Flow is still produced
inside the model because the checkpoint and reverse algorithm require the full
dual-task architecture, but flow is never returned by the public API or frontend.

The graph builder preserves the official fixed structure:

- `x`: `[8, 15]`
- `edge_index`: `[2, 24]`
- `edge_attr`: `[24, 9]`
- `u`: `[1, 2]`
- `chip_physics`: `[6, 7]`

No output inverse transform, Normalized, Offset, or DP 0 difference processing
is added by the application.

## Reverse Runtime

Reverse Prediction is fixed to 6 chips and runs as an asynchronous background task.
The worker process calls the vendored official tandem optimization functions
with the product defaults from the source script, uses the same seed44
checkpoint, and returns one final design. It does not read fixed user CSV files
or write shared model-source outputs.

Only one reverse task may run at a time. Task state and worker logs stay under
`.runtime/` and are not part of Git or release assets.

## Errors

Runtime errors use structured codes and do not expose local checkpoint paths,
source repository paths, Python tracebacks, or worker log paths in public
responses.
