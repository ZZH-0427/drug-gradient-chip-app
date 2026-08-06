[CmdletBinding()]
param(
    [int]$RuntimeRelocationTimeoutSeconds = 600
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function RepoRoot { return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }

. (Join-Path $PSScriptRoot "portable_runtime.ps1")

try {
    $root = RepoRoot
    $logsDir = Join-Path (Join-Path $root ".runtime") "logs"
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONUTF8 = "1"
    Ensure-PortableRuntimeReady -Root $root -LogsDir $logsDir -TimeoutSeconds $RuntimeRelocationTimeoutSeconds
    exit 0
} catch {
    Write-Host "[error] $($_.Exception.Message)"
    Write-Host "Runtime initialization logs: $(Join-Path (Join-Path (RepoRoot) '.runtime') 'logs')"
    exit 1
}
