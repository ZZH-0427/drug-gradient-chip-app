[CmdletBinding()]
param(
    [switch]$CleanStale
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status([string]$Name, [object]$Value) {
    Write-Host ("{0}: {1}" -f $Name, $Value)
}

. (Join-Path $PSScriptRoot "local_app_lifecycle.ps1")

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
    $root = Get-LocalAppRepositoryRoot
    $statePath = Get-LocalAppStatePath -Root $root
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Status "status" "stopped"
        Write-Status "state_file" $statePath
        exit 0
    }

    $state = Read-LocalAppState -Path $statePath
    $targetProcessId = [int]$state.pid
    $processInfo = Get-LocalAppProcessInfo -TargetProcessId $targetProcessId
    $exists = $null -ne $processInfo
    $validProcess = Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $processInfo

    if (-not $validProcess) {
        Write-Status "status" "stale"
        Write-Status "pid" $targetProcessId
        Write-Status "process_exists" $exists
        Write-Status "project_process" $false
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
    if (Get-Member -InputObject $state -Name runtime_mode -MemberType NoteProperty) {
        Write-Status "runtime_mode" $state.runtime_mode
    }
    if (Get-Member -InputObject $state -Name application_version -MemberType NoteProperty) {
        Write-Status "application_version" $state.application_version
    }
    if (Get-Member -InputObject $state -Name build_commit -MemberType NoteProperty) {
        Write-Status "build_commit" $state.build_commit
    }
    Write-Status "process_exists" $exists
    Write-Status "project_process" $true
    Write-Status "health" $healthOk
    Write-Status "model_ready" $modelReady
    Write-Status "logs" "$($state.stdout_log), $($state.stderr_log)"
    exit 0
} catch {
    Write-Host "[error] $($_.Exception.Message)"
    exit 1
}
