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

function Stop-ReverseWorkers([string]$Root) {
    $normalizedRoot = ConvertTo-LocalAppNormalizedPath -Path $Root
    $workers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $line = [string]$_.CommandLine
            $line -and
                (Test-LocalAppCommandLineContains -CommandLine $line -Needle "-m app.model_runtime.reverse_worker") -and
                (Test-LocalAppCommandLineContains -CommandLine $line -Needle "--application-root") -and
                (Test-LocalAppCommandLineContains -CommandLine $line -Needle $normalizedRoot)
        })
    foreach ($worker in @($workers)) {
        Write-Info "Stopping reverse worker PID $($worker.ProcessId)."
        Stop-Process -Id ([int]$worker.ProcessId) -Force -ErrorAction SilentlyContinue
    }

    $portablePython = Join-Path $Root "runtime\python.exe"
    $taskRoot = Join-Path (Join-Path $Root ".runtime") "reverse_tasks"
    if (-not (Test-Path -LiteralPath $taskRoot)) { return }
    foreach ($statePath in Get-ChildItem -LiteralPath $taskRoot -Recurse -Force -File -Filter "state.json" -ErrorAction SilentlyContinue) {
        try {
            $state = Get-Content -LiteralPath $statePath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            continue
        }
        if ($null -eq (Get-Member -InputObject $state -Name "pid" -MemberType NoteProperty)) { continue }
        if ($null -eq (Get-Member -InputObject $state -Name "status" -MemberType NoteProperty)) { continue }
        if ([string]$state.status -eq "completed") { continue }
        $workerPid = 0
        if (-not [int]::TryParse([string]$state.pid, [ref]$workerPid) -or $workerPid -le 0) { continue }
        $processInfo = Get-LocalAppProcessInfo -TargetProcessId $workerPid
        if ($null -eq $processInfo) { continue }
        $line = [string]$processInfo.CommandLine
        $matchesCommandLine = (Test-LocalAppCommandLineContains -CommandLine $line -Needle "-m app.model_runtime.reverse_worker") -and
            (Test-LocalAppCommandLineContains -CommandLine $line -Needle "--application-root") -and
            (Test-LocalAppCommandLineContains -CommandLine $line -Needle $normalizedRoot)
        $matchesPortablePython = (Test-Path -LiteralPath $portablePython) -and
            (Test-LocalAppPathEqual -Left ([string]$processInfo.ExecutablePath) -Right $portablePython)
        if ($matchesCommandLine -or $matchesPortablePython) {
            Write-Info "Stopping reverse worker PID $workerPid from task state."
            Stop-Process -Id $workerPid -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
    $root = Get-LocalAppRepositoryRoot
    $statePath = Get-LocalAppStatePath -Root $root
    if (-not (Test-Path -LiteralPath $statePath)) {
        Stop-ReverseWorkers -Root $root
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
        Stop-ReverseWorkers -Root $root
        Write-Info "Stale PID found; state file removed."
        exit 0
    }

    if (-not (Test-LocalAppProcessIdentity -State $state -Root $root -ProcessInfo $processInfo)) {
        throw "PID $targetProcessId is not this project's Uvicorn process; refusing to stop it."
    }

    Stop-Process -Id $targetProcessId -ErrorAction Stop
    Stop-ReverseWorkers -Root $root
    Wait-PortReleased -Port ([int]$state.port)
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    Write-Info "Application stopped. Logs remain under .runtime/logs."
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
