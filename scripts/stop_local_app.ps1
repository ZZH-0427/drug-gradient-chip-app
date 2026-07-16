[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) {
    Write-Host "[info] $Message"
}

function Write-Fail([string]$Message) {
    Write-Host "[error] $Message"
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

function Wait-PortReleased([int]$Port) {
    $deadline = (Get-Date).AddSeconds(20)
    do {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $connection) {
            return
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Port $Port was not released in time."
}

try {
    $root = Get-RepositoryRoot
    $statePath = Get-StatePath -Root $root
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Info "Application is not running."
        exit 0
    }

    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $stateRoot = (Resolve-Path -LiteralPath ([string]$state.repository_root)).Path
    if ($stateRoot -ne $root) {
        throw "State repository_root does not match current project; refusing to stop process."
    }

    $targetProcessId = [int]$state.pid
    $process = Get-Process -Id $targetProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        Write-Info "Stale PID found; state file removed."
        exit 0
    }

    $commandLine = Get-ProcessCommandLine -TargetProcessId $targetProcessId
    if ($process.ProcessName -notlike "python*" -or $commandLine -notlike "*uvicorn*" -or $commandLine -notlike "*backend.app.main:app*") {
        throw "PID $targetProcessId is not this project's Uvicorn process; refusing to stop it."
    }

    Stop-Process -Id $targetProcessId -ErrorAction Stop
    Wait-PortReleased -Port ([int]$state.port)
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    Write-Info "Application stopped. Logs remain under .runtime/logs."
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
