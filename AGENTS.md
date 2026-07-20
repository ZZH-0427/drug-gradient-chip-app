# Agent Guide

## Project Goal

Wrap the existing forward model as a visualizable application runtime.

## Current Stage

Only the forward model runtime is implemented.

## Core Rules

- Do not train models.
- Do not modify the original model repository.
- Do not implement Normalized or Offset business processing.
- Do not guess model input order.
- Do not guess chip category encodings.
- Load model checkpoints once during runtime initialization.
- Read all model paths from configuration.
- Keep model core logic independent from CSV.
- Keep CSV limited to the input adapter layer.
- Add tests when business logic changes.
- Keep the golden sample passing.

## Prohibited

- Hardcoding the original `D:\pytorch_geometric-master` path in Python code.
- Reloading checkpoints on every prediction request.
- Modifying original checkpoints.
- Placing model logic in future API route modules.
- Replacing real forward prediction with mock output.
- Claiming completion when tests fail.
