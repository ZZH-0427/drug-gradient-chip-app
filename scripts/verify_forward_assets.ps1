param(
    [string]$AssetRoot,
    [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Join-Relative {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Relative
    )
    $parts = $Relative -split "/"
    $path = $Root
    foreach ($part in $parts) {
        $path = Join-Path $path $part
    }
    return $path
}

function Assert-Sequence {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )
    $actualText = $Actual -join ","
    if ($actualText -ne $Expected) {
        Write-Error "Unexpected ${DisplayName}: $actualText"
        exit 1
    }
}

$repoRoot = Get-RepoRoot
if ([string]::IsNullOrWhiteSpace($AssetRoot)) {
    $AssetRoot = Join-Path $repoRoot "model_assets\physics_gnn"
}
$assetRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($AssetRoot)
$manifestPath = Join-Path $assetRootPath "manifest.json"

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    Write-Error "Manifest not found: $manifestPath"
    exit 1
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema_version -ne 1) {
    Write-Error "Unsupported manifest schema_version: $($manifest.schema_version)"
    exit 1
}

$expectedHash = "f6f80287d3b04145daf01c5267f7b304cca88bd2331d380063f49d43b6ead0cc"
if ([string]$manifest.model_family -ne "PhysicsGuidedDualTaskGNN") {
    Write-Error "Unexpected model family: $($manifest.model_family)"
    exit 1
}
Assert-Sequence -Actual $manifest.supported_forward_chip_counts -Expected "4,5,6,7,8,9,10" -DisplayName "forward chip counts"
Assert-Sequence -Actual $manifest.supported_reverse_chip_counts -Expected "6" -DisplayName "reverse chip counts"
if ([string]$manifest.forward_graph_mode -ne "routed") {
    Write-Error "Unexpected forward graph mode: $($manifest.forward_graph_mode)"
    exit 1
}
if ($null -eq $manifest.forward_routes) {
    Write-Error "Manifest is missing forward_routes."
    exit 1
}
$fixedSixRoute = $manifest.forward_routes.fixed_six
$zeroShotRoute = $manifest.forward_routes.zero_shot
if ($null -eq $fixedSixRoute) {
    Write-Error "Manifest is missing forward_routes.fixed_six."
    exit 1
}
if ($null -eq $zeroShotRoute) {
    Write-Error "Manifest is missing forward_routes.zero_shot."
    exit 1
}
Assert-Sequence -Actual $fixedSixRoute.chip_counts -Expected "6" -DisplayName "fixed-six route chip counts"
if ([string]$fixedSixRoute.graph_mode -ne "fixed") {
    Write-Error "Unexpected fixed-six route graph mode: $($fixedSixRoute.graph_mode)"
    exit 1
}
Assert-Sequence -Actual $zeroShotRoute.chip_counts -Expected "4,5,7,8,9,10" -DisplayName "zero-shot route chip counts"
if ([string]$zeroShotRoute.graph_mode -ne "dynamic") {
    Write-Error "Unexpected zero-shot route graph mode: $($zeroShotRoute.graph_mode)"
    exit 1
}
if ([string]$zeroShotRoute.scale_extension -ne "zero_shot") {
    Write-Error "Unexpected zero-shot route scale extension: $($zeroShotRoute.scale_extension)"
    exit 1
}
if ([int]$manifest.training_chip_count -ne 6) {
    Write-Error "Unexpected training chip count: $($manifest.training_chip_count)"
    exit 1
}
if ([string]$manifest.public_forward_output -ne "concentration_only") {
    Write-Error "Unexpected public output: $($manifest.public_forward_output)"
    exit 1
}
$checkpointFile = [string]$manifest.checkpoint_file
if ($checkpointFile -ne "best_concentration_checkpoint.pt") {
    Write-Error "Unexpected checkpoint file: $checkpointFile"
    exit 1
}
$path = Join-Path $assetRootPath $checkpointFile
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Write-Error "Asset missing: $checkpointFile"
    exit 1
}
$item = Get-Item -LiteralPath $path
if ($item.Length -le 0) {
    Write-Error "Asset is empty: $checkpointFile"
    exit 1
}
if ($item.Length -ne [int64]$manifest.checkpoint_size_bytes) {
    Write-Error "Size mismatch for ${checkpointFile}: expected $($manifest.checkpoint_size_bytes), got $($item.Length)"
    exit 1
}
$hash = Get-Sha256 -Path $path
if ($hash -ne $expectedHash -or $hash -ne [string]$manifest.checkpoint_sha256) {
    Write-Error "SHA-256 mismatch for $checkpointFile"
    exit 1
}

& $PythonPath -c "import torch; ck=torch.load(r'$path', map_location='cpu', weights_only=False); assert ck['architecture']['model_type']=='PhysicsGuidedDualTaskGNN'; assert ck['architecture']['in_channels']==15; assert ck['architecture']['edge_dim']==9; assert ck['architecture']['global_feature_dim']==2; required={'x_mean','x_std','edge_mean','edge_std','u_mean','u_std','chip_physics_mean','chip_physics_std','flow_log_mean','flow_log_std'}; assert required.issubset(ck['normalizers'])"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Checkpoint CPU load or metadata validation failed."
    exit 1
}

Write-Host "model family: PhysicsGuidedDualTaskGNN"
Write-Host "checkpoint count: 1"
Write-Host "seed: 44"
Write-Host "forward graph mode: routed"
Write-Host "fixed-six route: chip_count 6, graph_mode fixed"
Write-Host "zero-shot route: chip_counts 4,5,7,8,9,10, graph_mode dynamic, scale_extension zero_shot"
Write-Host "hash validation: passed"
