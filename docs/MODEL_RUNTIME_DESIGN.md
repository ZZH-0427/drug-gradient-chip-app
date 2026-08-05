# Model Runtime Design

## Application Schema

The forward API accepts `chip_count` from 4 through 10 and defaults missing
`chip_count` to 6 for old clients. The request must contain exactly `chip_count`
chip rows with consecutive positions from 1 through N.

## Forward Runtime

The application uses the official dynamic `PhysicsGuidedDualTaskGNN` runtime
with one bundled checkpoint under `model_assets/physics_gnn/`. The checkpoint
was trained on six-chip data and is used for zero-shot scale extension to 4
through 10 chips. The public forward response contains one concentration value
per chip. Flow is still produced inside the model because the checkpoint and
reverse algorithm require the full dual-task architecture, but flow is never
returned by the public API or frontend.

The graph builder uses the official dynamic structure:

- `x`: `[N + 2, 15]`
- `edge_index`: `[2, 4N]`
- `edge_attr`: `[4N, 9]`
- `u`: `[1, 2]`
- `chip_physics`: `[N, 7]`

For N=6, the graph remains equivalent to the previous fixed-six runtime.
Positions 1 through N are encoded into the checkpoint training range 1 through
6 before normalization.

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
