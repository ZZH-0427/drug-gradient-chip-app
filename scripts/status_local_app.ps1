[CmdletBinding()]
param(
    [switch]$CleanStale
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status([string]$Name, [object]$Value) {
    Write-Host ("{0}: {1}" -f $Name, $Value)
}

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-StatePath([string]$Root) {
    return Join-Path (Join-Path $Root ".runtime") "app-state.json"
}

function Get-ProcessCommandLine([int]$TargetProcessId) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return ""
    }
    return [string]$process.CommandLine
}

function Test-Health([string]$Url) {
    try {
        $health = Invoke-RestMethod -Method Get -Uri "$Url/api/v1/health" -TimeoutSec 5
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

function Test-ModelReady([string]$Url) {
    try {
        $status = Invoke-RestMethod -Method Get -Uri "$Url/api/v1/model-status" -TimeoutSec 10
        return [bool]$status.ready
    } catch {
        return $false
    }
}

try {
    $root = Get-RepositoryRoot
    $statePath = Get-StatePath -Root $root
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Status "status" "stopped"
        Write-Status "state_file" $statePath
        exit 0
    }

    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $targetProcessId = [int]$state.pid
    $process = Get-Process -Id $targetProcessId -ErrorAction SilentlyContinue
    $exists = $null -ne $process
    $commandLine = if ($exists) { Get-ProcessCommandLine -TargetProcessId $targetProcessId } else { "" }
    $stateRoot = ""
    try {
        $stateRoot = (Resolve-Path -LiteralPath ([string]$state.repository_root)).Path
    } catch {
        $stateRoot = [string]$state.repository_root
    }
    $validProcess = $exists -and $stateRoot -eq $root -and $commandLine -like "*uvicorn*" -and $commandLine -like "*backend.app.main:app*"

    if (-not $validProcess) {
        Write-Status "status" "stale"
        Write-Status "pid" $targetProcessId
        Write-Status "process_exists" $exists
        Write-Status "url" $state.url
        Write-Status "logs" "$($state.stdout_log), $($state.stderr_log)"
        if ($CleanStale) {
            Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
            Write-Status "cleanup" "stale state file removed"
        }
        exit 0
    }

    $healthOk = Test-Health -Url ([string]$state.url)
    $modelReady = Test-ModelReady -Url ([string]$state.url)
    $status = if ($healthOk -and $modelReady) { "running" } else { "unhealthy" }

    Write-Status "status" $status
    Write-Status "pid" $targetProcessId
    Write-Status "url" $state.url
    Write-Status "port" $state.port
    Write-Status "process_exists" $exists
    Write-Status "health" $healthOk
    Write-Status "model_ready" $modelReady
    Write-Status "logs" "$($state.stdout_log), $($state.stderr_log)"
    exit 0
} catch {
    Write-Host "[error] $($_.Exception.Message)"
    exit 1
}
