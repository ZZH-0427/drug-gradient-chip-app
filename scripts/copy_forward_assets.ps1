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
    $DestinationRoot = Join-Path $repoRoot "model_assets\forward"
}

$sourceRootPath = (Resolve-Path -LiteralPath $SourceRoot).Path
$destinationRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DestinationRoot)

$assets = @(
    @{
        Role = "graph_template"
        Source = "GNN/Gnndata/physics_gnn_dataset.pt"
        Target = "graph_template/physics_gnn_dataset.pt"
    },
    @{
        Role = "checkpoint"
        Seed = 42
        Source = "GNN/Physics-GNN/model/ablation/data_only/seed_42/best_ablation_checkpoint.pt"
        Target = "checkpoints/seed_42/best_ablation_checkpoint.pt"
    },
    @{
        Role = "checkpoint"
        Seed = 52
        Source = "GNN/Physics-GNN/model/ablation/data_only/seed_52/best_ablation_checkpoint.pt"
        Target = "checkpoints/seed_52/best_ablation_checkpoint.pt"
    },
    @{
        Role = "checkpoint"
        Seed = 62
        Source = "GNN/Physics-GNN/model/ablation/data_only/seed_62/best_ablation_checkpoint.pt"
        Target = "checkpoints/seed_62/best_ablation_checkpoint.pt"
    },
    @{
        Role = "checkpoint"
        Seed = 72
        Source = "GNN/Physics-GNN/model/ablation/data_only/seed_72/best_ablation_checkpoint.pt"
        Target = "checkpoints/seed_72/best_ablation_checkpoint.pt"
    },
    @{
        Role = "checkpoint"
        Seed = 82
        Source = "GNN/Physics-GNN/model/ablation/data_only/seed_82/best_ablation_checkpoint.pt"
        Target = "checkpoints/seed_82/best_ablation_checkpoint.pt"
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

$manifestFiles = @()
foreach ($asset in $assets) {
    $targetPath = Join-Relative -Root $destinationRootPath -Relative $asset.Target
    $item = Get-Item -LiteralPath $targetPath
    $entry = [ordered]@{
        role = $asset.Role
    }
    if ($asset.ContainsKey("Seed")) {
        $entry.seed = $asset.Seed
    }
    $entry.relative_path = $asset.Target
    $entry.size_bytes = $item.Length
    $entry.sha256 = Get-Sha256 -Path $targetPath
    $manifestFiles += [PSCustomObject]$entry
}

$manifest = [ordered]@{
    schema_version = 1
    model_name = "forward-ensemble"
    ensemble_seeds = @(42, 52, 62, 72, 82)
    files = $manifestFiles
}

$manifestPath = Join-Path $destinationRootPath "manifest.json"
$json = $manifest | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($manifestPath, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Manifest written: $manifestPath"
