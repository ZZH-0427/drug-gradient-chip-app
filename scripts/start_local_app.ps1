[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$CondaEnvironment = "drug-chip",
    [ValidateSet("cpu", "cuda", "auto")]
    [string]$Device = "cpu",
    [string]$PythonPath = "",
    [switch]$RebuildFrontend,
    [switch]$NoBrowser,
    [switch]$Foreground,
    [int]$StartupTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$Message) { Write-Host "[info] $Message" }
function Fail([string]$Message) { Write-Host "[error] $Message" }
function RepoRoot { return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
function StatePath([string]$Root) { return Join-Path (Join-Path $Root ".runtime") "app-state.json" }
function ProcLine([int]$TargetProcessId) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return "" }
    return [string]$process.CommandLine
}
function IsOurState($State, [string]$Root) {
    if ($null -eq $State) { return $false }
    $targetProcessId = [int]$State.pid
    if ($null -eq (Get-Process -Id $targetProcessId -ErrorAction SilentlyContinue)) { return $false }
    $stateRoot = (Resolve-Path -LiteralPath ([string]$State.repository_root)).Path
    $line = ProcLine -TargetProcessId $targetProcessId
    return $stateRoot -eq $Root -and $line -like "*uvicorn*" -and $line -like "*backend.app.main:app*"
}
function ReadState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
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
function AssertPortAvailable([string]$BindAddress, [int]$TargetPort, [string]$StateFile, [string]$Root) {
    $state = ReadState -Path $StateFile
    if (IsOurState -State $state -Root $Root) {
        Info "Application is already running: $($state.url)"
        if (-not $NoBrowser) { Start-Process $state.url | Out-Null }
        exit 0
    }
    if ($null -ne $state) {
        Info "Removing stale state file."
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    }
    $connection = Get-NetTCPConnection -LocalAddress $BindAddress -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
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
        $ci = Start-Process -FilePath $npm.Source -ArgumentList @("ci") -WorkingDirectory $frontend -Wait -PassThru -NoNewWindow
        if ($ci.ExitCode -ne 0) { throw "npm ci failed." }
    }
    Info "Running npm run build."
    $build = Start-Process -FilePath $npm.Source -ArgumentList @("run", "build") -WorkingDirectory $frontend -Wait -PassThru -NoNewWindow
    if ($build.ExitCode -ne 0) { throw "frontend build failed." }
    $distIndex = Join-Path $frontend "dist\index.html"
    $distAssets = Join-Path $frontend "dist\assets"
    if (-not (Test-Path -LiteralPath $distIndex) -or -not (Test-Path -LiteralPath $distAssets)) {
        throw "frontend build output is incomplete."
    }
    if ((Get-Item -LiteralPath $distIndex).Length -le 0) { throw "frontend dist index.html is empty." }
}
function WaitJson([string]$Uri, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try { return Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 5 } catch { Start-Sleep -Milliseconds 800 }
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Uri"
}

try {
    $root = RepoRoot
    foreach ($required in @("backend\app\main.py", "frontend\package.json", "model_assets\forward\manifest.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $required))) { throw "Missing required path: $required" }
    }
    $runtimeDir = Join-Path $root ".runtime"
    $logsDir = Join-Path $runtimeDir "logs"
    $stateFile = StatePath -Root $root
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

    AssertPortAvailable -BindAddress $HostAddress -TargetPort $Port -StateFile $stateFile -Root $root
    Info "Verifying bundled model assets."
    $verifyArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\verify_forward_assets.ps1"))
    $verify = Start-Process -FilePath "powershell.exe" -ArgumentList $verifyArgs -WorkingDirectory $root -Wait -PassThru -NoNewWindow
    if ($verify.ExitCode -ne 0) { throw "model asset verification failed." }

    $python = ResolvePython -EnvironmentName $CondaEnvironment -OverridePath $PythonPath
    BuildFrontend -Root $root -Force:$RebuildFrontend

    $stdoutLog = Join-Path $logsDir "backend.stdout.log"
    $stderrLog = Join-Path $logsDir "backend.stderr.log"
    $url = "http://$HostAddress`:$Port"
    $env:MODEL_SOURCE_ROOT = ""
    $env:FORWARD_MODEL_DEVICE = $Device
    $env:SERVE_FRONTEND = "true"
    $env:FRONTEND_DIST_DIR = Join-Path $root "frontend\dist"
    $args = @("-m", "uvicorn", "backend.app.main:app", "--host", $HostAddress, "--port", [string]$Port)
    if ($Foreground) {
        Info "Starting foreground app at $url"
        & $python @args
        exit $LASTEXITCODE
    }
    Info "Starting app at $url"
    $process = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
    $state = [ordered]@{
        schema_version = 1
        pid = $process.Id
        host = $HostAddress
        port = $Port
        url = $url
        repository_root = $root
        python_executable = $python
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding UTF8
    try {
        WaitJson -Uri "$url/api/v1/health" -TimeoutSeconds $StartupTimeoutSeconds | Out-Null
        $model = WaitJson -Uri "$url/api/v1/model-status" -TimeoutSeconds $StartupTimeoutSeconds
        if (-not $model.ready) { throw "model-status is not ready." }
    } catch {
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
        throw
    }
    Info "Application started: $url"
    if (-not $NoBrowser) { Start-Process $url | Out-Null }
    exit 0
} catch {
    Fail $_.Exception.Message
    exit 1
}
