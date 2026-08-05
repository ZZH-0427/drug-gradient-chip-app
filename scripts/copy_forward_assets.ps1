param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [string]$DestinationRoot,

    [switch]$Force
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

$repoRoot = Get-RepoRoot
if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path $repoRoot "model_assets\physics_gnn"
}

$sourceRootPath = (Resolve-Path -LiteralPath $SourceRoot).Path
$destinationRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestinationRoot)

$assets = @(
    @{
        Role = "checkpoint"
        Source = "GNN/Physics-GNN/model/experiment_D_balanced_medium_weight/seed_44/best_concentration_checkpoint.pt"
        Target = "best_concentration_checkpoint.pt"
    }
)

$missing = @()
foreach ($asset in $assets) {
    $sourcePath = Join-Relative -Root $sourceRootPath -Relative $asset.Source
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        $missing += $sourcePath
    }
}

if ($missing.Count -gt 0) {
    Write-Error ("Missing required source assets:`n" + ($missing -join "`n"))
    exit 1
}

foreach ($asset in $assets) {
    $sourcePath = Join-Relative -Root $sourceRootPath -Relative $asset.Source
    $targetPath = Join-Relative -Root $destinationRootPath -Relative $asset.Target
    $targetDir = Split-Path -Parent $targetPath
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

    $sourceHash = Get-Sha256 -Path $sourcePath
    if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
        $targetHash = Get-Sha256 -Path $targetPath
        if ($sourceHash -eq $targetHash) {
            Write-Host "Exists and matches: $($asset.Target)"
            continue
        }
        if (-not $Force) {
            Write-Error "Target exists with a different SHA-256. Use -Force to overwrite: $targetPath"
            exit 1
        }
    }

    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force:$Force
    $copiedHash = Get-Sha256 -Path $targetPath
    if ($sourceHash -ne $copiedHash) {
        Write-Error "Hash mismatch after copy: $($asset.Target)"
        exit 1
    }
    Write-Host "Copied: $($asset.Target)"
}

$checkpointPath = Join-Relative -Root $destinationRootPath -Relative "best_concentration_checkpoint.pt"
$checkpoint = Get-Item -LiteralPath $checkpointPath
$manifest = [ordered]@{
    schema_version = 1
    model_family = "PhysicsGuidedDualTaskGNN"
    checkpoint_file = "best_concentration_checkpoint.pt"
    checkpoint_sha256 = Get-Sha256 -Path $checkpointPath
    checkpoint_size_bytes = $checkpoint.Length
    supported_forward_chip_counts = @(4, 5, 6, 7, 8, 9, 10)
    supported_reverse_chip_counts = @(6)
    forward_graph_mode = "dynamic"
    training_chip_count = 6
    scale_extension = "zero_shot"
    public_forward_output = "concentration_only"
    internal_outputs = @("concentration", "flow")
}

$manifestPath = Join-Path $destinationRootPath "manifest.json"
$json = $manifest | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($manifestPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Manifest written: $manifestPath"
