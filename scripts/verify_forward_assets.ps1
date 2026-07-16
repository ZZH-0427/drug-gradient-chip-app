param(
    [string]$AssetRoot
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
if ([string]::IsNullOrWhiteSpace($AssetRoot)) {
    $AssetRoot = Join-Path $repoRoot "model_assets\forward"
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

$expectedSeeds = @(42, 52, 62, 72, 82)
$actualSeeds = @($manifest.ensemble_seeds | ForEach-Object { [int]$_ })
if (($actualSeeds -join ",") -ne ($expectedSeeds -join ",")) {
    Write-Error "Unexpected ensemble seeds: $($actualSeeds -join ',')"
    exit 1
}

$checkpointSeeds = @($manifest.files | Where-Object { $_.role -eq "checkpoint" } | ForEach-Object { [int]$_.seed } | Sort-Object)
if (($checkpointSeeds -join ",") -ne ($expectedSeeds -join ",")) {
    Write-Error "Unexpected checkpoint seeds: $($checkpointSeeds -join ',')"
    exit 1
}

$graphCount = @($manifest.files | Where-Object { $_.role -eq "graph_template" }).Count
if ($graphCount -ne 1) {
    Write-Error "Expected exactly one graph template, found $graphCount"
    exit 1
}

foreach ($file in $manifest.files) {
    $path = Join-Relative -Root $assetRootPath -Relative $file.relative_path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-Error "Asset missing: $($file.relative_path)"
        exit 1
    }
    $item = Get-Item -LiteralPath $path
    if ($item.Length -le 0) {
        Write-Error "Asset is empty: $($file.relative_path)"
        exit 1
    }
    if ($item.Length -ne [int64]$file.size_bytes) {
        Write-Error "Size mismatch for $($file.relative_path): expected $($file.size_bytes), got $($item.Length)"
        exit 1
    }
    $hash = Get-Sha256 -Path $path
    if ($hash -ne [string]$file.sha256) {
        Write-Error "SHA-256 mismatch for $($file.relative_path)"
        exit 1
    }
}

Write-Host "graph template: passed"
Write-Host "checkpoint count: $($checkpointSeeds.Count)"
Write-Host "seeds: $($actualSeeds -join ',')"
Write-Host "hash validation: passed"
