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

. (Join-Path $PSScriptRoot "local_app_lifecycle.ps1")

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
    $root = Get-LocalAppRepositoryRoot
    $statePath = Get-LocalAppStatePath -Root $root
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Info "Application is not running."
        exit 0
    }

    $state = Read-LocalAppState -Path $statePath
    if (-not (Test-LocalAppPathEqual -Left ([string]$state.application_root) -Right $root)) {
        throw "State repository_root does not match current project; refusing to stop process."
    }

    $targetProcessId = [int]$state.pid
    $processInfo = Get-LocalAppProcessInfo -TargetProcessId $targetProcessId
    if ($null -eq $processInfo) {
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        Write-Info "Stale PID found; state file removed."
        exit 0
    }

    if (-not (Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $processInfo)) {
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
