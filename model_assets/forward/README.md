# Forward Model Assets

This directory holds the local runtime asset layout for the verified forward
model ensemble.

Expected local files:

- `graph_template/physics_gnn_dataset.pt`
- `checkpoints/seed_42/best_ablation_checkpoint.pt`
- `checkpoints/seed_52/best_ablation_checkpoint.pt`
- `checkpoints/seed_62/best_ablation_checkpoint.pt`
- `checkpoints/seed_72/best_ablation_checkpoint.pt`
- `checkpoints/seed_82/best_ablation_checkpoint.pt`

The `.pt` files are local runtime assets and are ignored by Git. The committed
`manifest.json` records their expected sizes and SHA-256 hashes for integrity
verification.

To provision the assets from a read-only model source directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\copy_forward_assets.ps1 `
  -SourceRoot "C:\path\to\pytorch_geometric-master"
```

To verify the local copies:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_forward_assets.ps1
```
