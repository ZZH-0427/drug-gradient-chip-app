[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$CondaEnvironment = "drug-chip",
    [ValidateSet("cpu", "cuda", "auto")]
    [string]$Device = "cpu",
    [string]$PythonPath = "",
    [ValidateSet("Auto", "Development", "Portable")]
    [string]$RuntimeMode = "Auto",
    [switch]$RebuildFrontend,
    [switch]$NoBrowser,
    [switch]$Foreground,
    [string]$BrowserCommand = "",
    [int]$StartupTimeoutSeconds = 90,
    [int]$ChildProcessTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$Message) { Write-Host "[info] $Message" }
function Fail([string]$Message) { Write-Host "[error] $Message" }
function Warn([string]$Message) { Write-Warning $Message }
. (Join-Path $PSScriptRoot "local_app_lifecycle.ps1")
function RepoRoot { return Get-LocalAppRepositoryRoot }
function StatePath([string]$Root) { return Get-LocalAppStatePath -Root $Root }
function RuntimeReadyMarkerPath([string]$Root) { return Join-Path (Join-Path $Root "runtime") ".conda-unpacked" }
function Quote-ProcessArgument([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\"') + '"'
}
function InvokeProcessWithTimeout {
    param(
        [Parameter(Mandatory = $true)] [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [int]$TimeoutSeconds = 300,
        [string]$RedirectStandardOutput = "",
        [string]$RedirectStandardError = "",
        [switch]$NoNewWindow
    )
    if ($TimeoutSeconds -le 0) { throw "Process timeout must be positive." }
    $startParams = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentList
        PassThru = $true
    }
    if ($WorkingDirectory.Trim()) { $startParams["WorkingDirectory"] = $WorkingDirectory }
    if ($RedirectStandardOutput.Trim()) { $startParams["RedirectStandardOutput"] = $RedirectStandardOutput }
    if ($RedirectStandardError.Trim()) { $startParams["RedirectStandardError"] = $RedirectStandardError }
    if ($NoNewWindow) { $startParams["NoNewWindow"] = $true }
    $process = Start-Process @startParams
    $null = $process.Handle
    if ($process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.WaitForExit(1000) | Out-Null
        $process.Refresh()
        return $process
    }
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "Process timed out after ${TimeoutSeconds}s: $FilePath $($ArgumentList -join ' ')"
}
function ResolveRuntimeMode([string]$Root, [string]$RequestedMode) {
    if ($RequestedMode -ne "Auto") { return $RequestedMode.ToLowerInvariant() }
    $portablePython = Join-Path $Root "runtime\python.exe"
    $buildInfo = Join-Path $Root "BUILD_INFO.json"
    $distIndex = Join-Path $Root "frontend\dist\index.html"
    if ((Test-Path -LiteralPath $portablePython) -and (Test-Path -LiteralPath $buildInfo) -and (Test-Path -LiteralPath $distIndex)) {
        return "portable"
    }
    return "development"
}
function ProcLine([int]$TargetProcessId) {
    $process = Get-LocalAppProcessInfo -TargetProcessId $TargetProcessId
    if ($null -eq $process) { return "" }
    return [string]$process.CommandLine
}
function IsOurState($State, [string]$Root) {
    if ($null -eq $State) { return $false }
    return Test-LocalAppProcessIdentity -State $State -Root $Root
}
function ReadState([string]$Path) {
    return Read-LocalAppState -Path $Path
}
function ResolvePython([string]$EnvironmentName, [string]$OverridePath) {
    if ($OverridePath.Trim()) {
        $python = (Resolve-Path -LiteralPath $OverridePath).Path
        & $python --version | Out-Null
        return $python
    }
    if ($env:CONDA_DEFAULT_ENV -eq $EnvironmentName) {
        $current = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $current) {
            & $current.Source --version | Out-Null
            return $current.Source
        }
    }
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -eq $conda) { throw "conda was not found; use -PythonPath or create the environment." }
    $envList = (& $conda.Source env list --json) | ConvertFrom-Json
    foreach ($envPath in $envList.envs) {
        if ((Split-Path -Leaf ([string]$envPath)) -eq $EnvironmentName) {
            $python = Join-Path ([string]$envPath) "python.exe"
            if (Test-Path -LiteralPath $python) {
                & $python --version | Out-Null
                return $python
            }
        }
    }
    throw "Conda environment '$EnvironmentName' was not found."
}
function ResolvePortablePython([string]$Root) {
    $python = Join-Path $Root "runtime\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { throw "Portable runtime python.exe was not found: $python" }
    & $python --version | Out-Null
    return $python
}
function Write-JsonAtomically([string]$Path, [object]$Value) {
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temp = Join-Path $directory (".tmp-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        $Value | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
function ShowCondaUnpackLogTail([string]$StdoutLog, [string]$StderrLog) {
    try {
        if (Test-Path -LiteralPath $StderrLog) {
            $stderr = @(Get-Content -LiteralPath $StderrLog -Tail 30 -ErrorAction SilentlyContinue)
            if ($stderr.Count -gt 0) {
                Write-Host "[conda-unpack stderr tail]"
                $stderr | ForEach-Object { Write-Host $_ }
            }
        }
        if (Test-Path -LiteralPath $StdoutLog) {
            $stdout = @(Get-Content -LiteralPath $StdoutLog -Tail 30 -ErrorAction SilentlyContinue)
            if ($stdout.Count -gt 0) {
                Write-Host "[conda-unpack stdout tail]"
                $stdout | ForEach-Object { Write-Host $_ }
            }
        }
    } catch {
        Warn "Could not read conda-unpack logs: $($_.Exception.Message)"
    }
}
function EnsurePortableRuntimeReady([string]$Root, [string]$LogsDir) {
    $runtimeRoot = (Resolve-Path -LiteralPath (Join-Path $Root "runtime")).Path
    $applicationRoot = (Resolve-Path -LiteralPath $Root).Path
    $marker = RuntimeReadyMarkerPath -Root $Root
    if (Test-Path -LiteralPath $marker) {
        $payload = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ([string]$payload.application_root -ne $applicationRoot -or [string]$payload.runtime_root -ne $runtimeRoot) {
            throw "Portable runtime was already initialized at a different path. Re-extract the original ZIP to the target location instead of moving an initialized directory."
        }
        Info "Portable runtime is already relocated."
        return
    }

    $condaUnpack = Join-Path $runtimeRoot "Scripts\conda-unpack.exe"
    if (-not (Test-Path -LiteralPath $condaUnpack)) {
        throw "Portable runtime relocation tool was not found: $condaUnpack"
    }
    $stdoutLog = Join-Path $LogsDir "conda-unpack.stdout.log"
    $stderrLog = Join-Path $LogsDir "conda-unpack.stderr.log"
    Info "Relocating portable runtime for this directory."
    $process = InvokeProcessWithTimeout -FilePath $condaUnpack -WorkingDirectory $Root -TimeoutSeconds $ChildProcessTimeoutSeconds -NoNewWindow -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    if ($process.ExitCode -ne 0) {
        ShowCondaUnpackLogTail -StdoutLog $stdoutLog -StderrLog $stderrLog
        throw "Portable runtime relocation failed with exit code $($process.ExitCode)."
    }
    Remove-EditableAppInstall -RuntimeRoot $runtimeRoot
    Write-JsonAtomically -Path $marker -Value ([ordered]@{
        schema_version = 1
        application_root = $applicationRoot
        runtime_root = $runtimeRoot
        completed_at = (Get-Date).ToUniversalTime().ToString("o")
    })
    Info "Portable runtime relocation completed."
}
function Remove-EditableAppInstall([string]$RuntimeRoot) {
    $sitePackages = Join-Path $RuntimeRoot "Lib\site-packages"
    if (-not (Test-Path -LiteralPath $sitePackages)) { return }
    foreach ($pattern in @(
        "__editable__.drug_gradient_chip_app-*.pth",
        "__editable___drug_gradient_chip_app_*.py",
        "drug_gradient_chip_app-*.dist-info"
    )) {
        Get-ChildItem -LiteralPath $sitePackages -Force -Filter $pattern -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop }
    }
}
function AssertPortAvailable([string]$BindAddress, [int]$TargetPort, [string]$StateFile, [string]$Root) {
    $state = ReadState -Path $StateFile
    if (IsOurState -State $state -Root $Root) {
        Info "Application is already running: $($state.url)"
        if (-not $NoBrowser) { OpenBrowserSafely -Url $state.url -CommandPath $BrowserCommand }
        exit 0
    }
    if ($null -ne $state) {
        Info "Removing stale state file."
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    }
    $connection = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $connection) {
        $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        $name = if ($null -eq $process) { "unknown" } else { $process.ProcessName }
        throw "Port $TargetPort is occupied by PID=$($connection.OwningProcess), process=$name."
    }
}
function NeedsFrontendBuild([string]$Root, [switch]$Force) {
    if ($Force) { return $true }
    $frontend = Join-Path $Root "frontend"
    $distIndex = Join-Path $frontend "dist\index.html"
    if (-not (Test-Path -LiteralPath $distIndex)) { return $true }
    $distTime = (Get-Item -LiteralPath $distIndex).LastWriteTimeUtc
    $paths = @("src", "public", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "index.html")
    foreach ($relative in $paths) {
        $path = Join-Path $frontend $relative
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $item = Get-Item -LiteralPath $path
        $files = if ($item -is [System.IO.FileInfo]) { @($item) } else { Get-ChildItem -LiteralPath $path -Recurse -File }
        foreach ($file in $files) {
            if ($file.LastWriteTimeUtc -gt $distTime) { return $true }
        }
    }
    return $false
}
function BuildFrontend([string]$Root, [switch]$Force) {
    $frontend = Join-Path $Root "frontend"
    if (-not (NeedsFrontendBuild -Root $Root -Force:$Force)) {
        Info "frontend/dist is up to date."
        return
    }
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $node -or $null -eq $npm) { throw "Node.js and npm.cmd are required to build frontend." }
    if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
        Info "Running npm ci."
        $ci = InvokeProcessWithTimeout -FilePath $npm.Source -ArgumentList @("ci") -WorkingDirectory $frontend -TimeoutSeconds $ChildProcessTimeoutSeconds -NoNewWindow
        if ($ci.ExitCode -ne 0) { throw "npm ci failed." }
    }
    Info "Running npm run build."
    $build = InvokeProcessWithTimeout -FilePath $npm.Source -ArgumentList @("run", "build") -WorkingDirectory $frontend -TimeoutSeconds $ChildProcessTimeoutSeconds -NoNewWindow
    if ($build.ExitCode -ne 0) { throw "frontend build failed." }
    $distIndex = Join-Path $frontend "dist\index.html"
    $distAssets = Join-Path $frontend "dist\assets"
    if (-not (Test-Path -LiteralPath $distIndex) -or -not (Test-Path -LiteralPath $distAssets)) {
        throw "frontend build output is incomplete."
    }
    if ((Get-Item -LiteralPath $distIndex).Length -le 0) { throw "frontend dist index.html is empty." }
}

function AssertPortableLayout([string]$Root) {
    foreach ($required in @("runtime\python.exe", "BUILD_INFO.json", "frontend\dist\index.html", "model_assets\physics_gnn\manifest.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $required))) { throw "Portable package is incomplete; missing $required" }
    }
    $index = Join-Path $Root "frontend\dist\index.html"
    if ((Get-Item -LiteralPath $index).Length -le 0) { throw "Portable frontend index.html is empty." }
}

function Get-PortablePath([string]$Root, [string]$OriginalPath) {
    $entries = New-Object System.Collections.Generic.List[string]
    foreach ($relative in @("runtime", "runtime\Scripts", "runtime\Library\bin", "runtime\Library\usr\bin", "runtime\Library\mingw-w64\bin")) {
        $path = Join-Path $Root $relative
        if (Test-Path -LiteralPath $path) { $entries.Add($path) }
    }
    if ($OriginalPath.Trim()) { $entries.Add($OriginalPath) }
    return ($entries -join ";")
}

function ShowLogTail([string]$StdoutLog, [string]$StderrLog) {
    try {
        if (Test-Path -LiteralPath $StderrLog) {
            $stderr = @(Get-Content -LiteralPath $StderrLog -Tail 30 -ErrorAction SilentlyContinue)
            if ($null -ne $stderr -and $stderr.Count -gt 0) {
                Write-Host "[stderr tail]"
                $stderr | ForEach-Object { Write-Host $_ }
                return
            }
        }
        if (Test-Path -LiteralPath $StdoutLog) {
            $stdout = @(Get-Content -LiteralPath $StdoutLog -Tail 30 -ErrorAction SilentlyContinue)
            if ($null -ne $stdout -and $stdout.Count -gt 0) {
                Write-Host "[stdout tail]"
                $stdout | ForEach-Object { Write-Host $_ }
            }
        }
    } catch {
        Warn "Could not read startup logs: $($_.Exception.Message)"
    }
}

function AssertProcessAlive([int]$TargetProcessId, [string]$StdoutLog, [string]$StderrLog) {
    $running = Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue
    if ($null -eq $running) {
        throw "Uvicorn exited before startup completed."
    }
}

function StartUvicornDetached {
    param(
        [Parameter(Mandatory = $true)] [string]$Python,
        [Parameter(Mandatory = $true)] [string[]]$UvicornArguments,
        [Parameter(Mandatory = $true)] [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)] [string]$RuntimeDirectory,
        [Parameter(Mandatory = $true)] [string]$LogsDirectory,
        [Parameter(Mandatory = $true)] [string]$StdoutLog,
        [Parameter(Mandatory = $true)] [string]$StderrLog,
        [int]$TimeoutSeconds = 30
    )
    $launcher = Join-Path $RuntimeDirectory "start-uvicorn-detached.py"
    $payloadPath = Join-Path $RuntimeDirectory ("uvicorn-launch-" + [guid]::NewGuid().ToString("N") + ".json")
    $launcherStdout = Join-Path $LogsDirectory "uvicorn-launcher.stdout.log"
    $launcherStderr = Join-Path $LogsDirectory "uvicorn-launcher.stderr.log"
    $launcherCode = @'
import json
import os
import subprocess
import sys

with open(sys.argv[1], "r", encoding="utf-8-sig") as handle:
    payload = json.load(handle)

stdout = open(payload["stdout_log"], "ab", buffering=0)
stderr = open(payload["stderr_log"], "ab", buffering=0)
creationflags = 0
if os.name == "nt":
    creationflags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    )

command = [sys.executable] + payload["args"]
try:
    process = subprocess.Popen(
        command,
        cwd=payload["working_directory"],
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        close_fds=True,
        env=os.environ.copy(),
        creationflags=creationflags,
    )
except OSError:
    if os.name != "nt" or not (creationflags & getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)):
        raise
    creationflags = creationflags & ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    process = subprocess.Popen(
        command,
        cwd=payload["working_directory"],
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        close_fds=True,
        env=os.environ.copy(),
        creationflags=creationflags,
    )

print(process.pid)
'@
    $payload = [ordered]@{
        args = $UvicornArguments
        working_directory = $WorkingDirectory
        stdout_log = $StdoutLog
        stderr_log = $StderrLog
    }
    try {
        $launcherCode | Set-Content -LiteralPath $launcher -Encoding UTF8
        $payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $payloadPath -Encoding UTF8
        Remove-Item -LiteralPath $launcherStdout, $launcherStderr -Force -ErrorAction SilentlyContinue
        $launcherProcess = InvokeProcessWithTimeout -FilePath $Python -ArgumentList @($launcher, $payloadPath) -WorkingDirectory $WorkingDirectory -TimeoutSeconds $TimeoutSeconds -NoNewWindow -RedirectStandardOutput $launcherStdout -RedirectStandardError $launcherStderr
        if ($launcherProcess.ExitCode -ne 0) {
            ShowLogTail -StdoutLog $launcherStdout -StderrLog $launcherStderr
            throw "Uvicorn launcher failed with exit code $($launcherProcess.ExitCode)."
        }
        $pidText = (Get-Content -LiteralPath $launcherStdout -Raw -ErrorAction Stop).Trim()
        $targetPid = 0
        if (-not [int]::TryParse($pidText, [ref]$targetPid) -or $targetPid -le 0) {
            throw "Uvicorn launcher did not report a valid PID."
        }
        return [pscustomobject]@{ Id = $targetPid }
    } finally {
        Remove-Item -LiteralPath $payloadPath -Force -ErrorAction SilentlyContinue
    }
}

function WaitJson([string]$Uri, [int]$TimeoutSeconds, [int]$TargetProcessId, [string]$StdoutLog, [string]$StderrLog) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        AssertProcessAlive -TargetProcessId $TargetProcessId -StdoutLog $StdoutLog -StderrLog $StderrLog
        try { return Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 5 } catch { Start-Sleep -Milliseconds 800 }
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function OpenBrowserSafely([string]$Url, [string]$CommandPath) {
    try {
        if ($CommandPath.Trim()) {
            if (-not (Test-Path -LiteralPath $CommandPath)) {
                throw "Browser command was not found: $CommandPath"
            }
            Start-Process -FilePath $CommandPath -ArgumentList @($Url) | Out-Null
        } else {
            Start-Process $Url | Out-Null
        }
    } catch {
        Warn "Application started, but the browser could not be opened: $($_.Exception.Message)"
    }
}

try {
    $root = RepoRoot
    foreach ($required in @("backend\app\main.py", "model_assets\physics_gnn\manifest.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $required))) { throw "Missing required path: $required" }
    }
    $resolvedRuntimeMode = ResolveRuntimeMode -Root $root -RequestedMode $RuntimeMode
    if ($resolvedRuntimeMode -eq "development" -and -not (Test-Path -LiteralPath (Join-Path $root "frontend\package.json"))) {
        throw "Missing required path: frontend\package.json"
    }
    $runtimeDir = Join-Path $root ".runtime"
    $logsDir = Join-Path $runtimeDir "logs"
    $stateFile = StatePath -Root $root
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
    AssertPortAvailable -BindAddress $HostAddress -TargetPort $Port -StateFile $stateFile -Root $root

    $originalPath = $env:Path
    $hadModelSourceRoot = Test-Path Env:MODEL_SOURCE_ROOT
    $originalModelSourceRoot = if ($hadModelSourceRoot) { $env:MODEL_SOURCE_ROOT } else { $null }
    $hadPythonNoUserSite = Test-Path Env:PYTHONNOUSERSITE
    $originalPythonNoUserSite = if ($hadPythonNoUserSite) { $env:PYTHONNOUSERSITE } else { $null }
    $hadPythonUtf8 = Test-Path Env:PYTHONUTF8
    $originalPythonUtf8 = if ($hadPythonUtf8) { $env:PYTHONUTF8 } else { $null }
    $hadPythonPath = Test-Path Env:PYTHONPATH
    $originalPythonPath = if ($hadPythonPath) { $env:PYTHONPATH } else { $null }
    $backendPath = Join-Path $root "backend"
    $env:PYTHONPATH = if ($hadPythonPath -and $originalPythonPath.Trim()) { "$backendPath;$originalPythonPath" } else { $backendPath }

    if ($resolvedRuntimeMode -eq "portable") {
        AssertPortableLayout -Root $root
        $env:Path = Get-PortablePath -Root $root -OriginalPath $originalPath
        $env:PYTHONNOUSERSITE = "1"
        $env:PYTHONUTF8 = "1"
        Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue
        EnsurePortableRuntimeReady -Root $root -LogsDir $logsDir
        $python = ResolvePortablePython -Root $root
        if ($RebuildFrontend) { Warn "-RebuildFrontend is ignored in portable mode." }
    } else {
        $python = ResolvePython -EnvironmentName $CondaEnvironment -OverridePath $PythonPath
        BuildFrontend -Root $root -Force:$RebuildFrontend
    }

    Info "Verifying bundled model assets."
    $verifyArgs = @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        (Join-Path $root "scripts\verify_forward_assets.ps1"),
        "-PythonPath",
        $python
    )
    $verifyProcessArgs = @($verifyArgs | ForEach-Object { Quote-ProcessArgument -Value $_ })
    $verify = InvokeProcessWithTimeout -FilePath "powershell.exe" -ArgumentList $verifyProcessArgs -WorkingDirectory $root -TimeoutSeconds $ChildProcessTimeoutSeconds -NoNewWindow
    if ($verify.ExitCode -ne 0) { throw "model asset verification failed." }

    $stdoutLog = Join-Path $logsDir "backend.stdout.log"
    $stderrLog = Join-Path $logsDir "backend.stderr.log"
    $identityFile = Join-Path $runtimeDir "app-process-identity.json"
    $identityToken = [guid]::NewGuid().ToString("N")
    $url = "http://$HostAddress`:$Port"
    $env:FORWARD_MODEL_DEVICE = $Device
    $env:SERVE_FRONTEND = "true"
    $env:FRONTEND_DIST_DIR = Join-Path $root "frontend\dist"
    $env:LOCAL_APP_IDENTITY_TOKEN = $identityToken
    $env:LOCAL_APP_IDENTITY_FILE = $identityFile
    $env:LOCAL_APP_APPLICATION_ROOT = $root
    $env:LOCAL_APP_MODULE = "backend.app.main:app"
    $env:LOCAL_APP_HOST = $HostAddress
    $env:LOCAL_APP_PORT = [string]$Port
    $args = @("-m", "uvicorn", "backend.app.main:app", "--app-dir", $root, "--host", $HostAddress, "--port", [string]$Port)
    if ($Foreground) {
        Info "Starting foreground app at $url"
        & $python @args
        exit $LASTEXITCODE
    }
    Info "Starting app at $url"
    $process = StartUvicornDetached -Python $python -UvicornArguments $args -WorkingDirectory $root -RuntimeDirectory $runtimeDir -LogsDirectory $logsDir -StdoutLog $stdoutLog -StderrLog $stderrLog -TimeoutSeconds $ChildProcessTimeoutSeconds
    $processInfo = $null
    $processInfoDeadline = (Get-Date).AddSeconds(10)
    do {
        $processInfo = Get-LocalAppProcessInfo -TargetProcessId $process.Id
        if ($null -ne $processInfo -and -not [string]::IsNullOrWhiteSpace($processInfo.CreationTimeUtc)) { break }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $processInfoDeadline)
    if ($null -eq $processInfo) {
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        throw "Could not read Uvicorn process identity after startup."
    }
    $state = [ordered]@{
        schema_version = 1
        pid = $process.Id
        process_start_time_utc = $processInfo.CreationTimeUtc
        executable_path = $processInfo.ExecutablePath
        application_root = $root
        app_module = "backend.app.main:app"
        runtime_mode = $resolvedRuntimeMode
        host = $HostAddress
        port = $Port
        url = $url
        repository_root = $root
        python_executable = $python
        identity_file = $identityFile
        identity_token = $identityToken
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
    }
    if ($resolvedRuntimeMode -eq "portable" -and (Test-Path -LiteralPath (Join-Path $root "BUILD_INFO.json"))) {
        $buildInfo = Get-Content -LiteralPath (Join-Path $root "BUILD_INFO.json") -Raw | ConvertFrom-Json
        $state["application_version"] = [string]$buildInfo.version
        $state["build_commit"] = [string]$buildInfo.build_commit
    }
    Write-LocalAppStateAtomically -Path $stateFile -Value $state
    try {
        WaitJson -Uri "$url/api/v1/health" -TimeoutSeconds $StartupTimeoutSeconds -TargetProcessId $process.Id -StdoutLog $stdoutLog -StderrLog $stderrLog | Out-Null
        $model = WaitJson -Uri "$url/api/v1/model-status" -TimeoutSeconds $StartupTimeoutSeconds -TargetProcessId $process.Id -StdoutLog $stdoutLog -StderrLog $stderrLog
        if (-not $model.ready) { throw "model-status is not ready." }
    } catch {
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
        ShowLogTail -StdoutLog $stdoutLog -StderrLog $stderrLog
        throw
    }
    Info "Application started: $url"
    if (-not $NoBrowser) { OpenBrowserSafely -Url $url -CommandPath $BrowserCommand }
    if ($resolvedRuntimeMode -eq "portable") {
        $env:Path = $originalPath
        if ($hadModelSourceRoot) { $env:MODEL_SOURCE_ROOT = $originalModelSourceRoot } else { Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue }
        if ($hadPythonNoUserSite) { $env:PYTHONNOUSERSITE = $originalPythonNoUserSite } else { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue }
        if ($hadPythonUtf8) { $env:PYTHONUTF8 = $originalPythonUtf8 } else { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue }
        if ($hadPythonPath) { $env:PYTHONPATH = $originalPythonPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    }
    exit 0
} catch {
    if (Get-Variable -Name resolvedRuntimeMode -ErrorAction SilentlyContinue) {
        if ($resolvedRuntimeMode -eq "portable") {
            if (Get-Variable -Name originalPath -ErrorAction SilentlyContinue) { $env:Path = $originalPath }
            if (Get-Variable -Name hadModelSourceRoot -ErrorAction SilentlyContinue) {
                if ($hadModelSourceRoot) { $env:MODEL_SOURCE_ROOT = $originalModelSourceRoot } else { Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue }
            }
            if (Get-Variable -Name hadPythonNoUserSite -ErrorAction SilentlyContinue) {
                if ($hadPythonNoUserSite) { $env:PYTHONNOUSERSITE = $originalPythonNoUserSite } else { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue }
            }
            if (Get-Variable -Name hadPythonUtf8 -ErrorAction SilentlyContinue) {
                if ($hadPythonUtf8) { $env:PYTHONUTF8 = $originalPythonUtf8 } else { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue }
            }
        }
        if (Get-Variable -Name hadPythonPath -ErrorAction SilentlyContinue) {
            if ($hadPythonPath) { $env:PYTHONPATH = $originalPythonPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
        }
    }
    Fail $_.Exception.Message
    exit 1
}
