[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$OutputRoot = "",
    [string]$CondaEnvironment = "drug-chip",
    [string]$BuildToolEnvironment = "drug-chip-portable-build",
    [switch]$SkipTests,
    [switch]$NoArchive,
    [switch]$KeepStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$Message) { Write-Host "[info] $Message" }
function Warn([string]$Message) { Write-Warning $Message }
function Fail([string]$Message) { Write-Host "[error] $Message" }
function RepoRoot { return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }

function Run-Checked([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [hashtable]$Environment = @{}) {
    $previous = @{}
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }
    try {
        $display = "$FilePath $($Arguments -join ' ')"
        Info $display
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -Wait -PassThru -NoNewWindow
        if ($process.ExitCode -ne 0) { throw "Command failed with exit code $($process.ExitCode): $display" }
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], "Process")
        }
    }
}

function Get-CondaCommand {
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($null -eq $conda) { throw "conda was not found." }
    return $conda.Source
}

function Get-CondaEnvPath([string]$Name) {
    $conda = Get-CondaCommand
    $envList = (& $conda env list --json) | ConvertFrom-Json
    foreach ($envPath in $envList.envs) {
        if ((Split-Path -Leaf ([string]$envPath)) -eq $Name) { return [string]$envPath }
    }
    throw "Conda environment '$Name' was not found."
}

function Get-CondaPython([string]$Name) {
    $envPath = Get-CondaEnvPath -Name $Name
    $python = Join-Path $envPath "python.exe"
    if (-not (Test-Path -LiteralPath $python)) { throw "python.exe was not found in '$Name'." }
    return $python
}

function Get-CommandOutput([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $output = & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $FilePath $($Arguments -join ' ')" }
    return ($output -join [Environment]::NewLine).Trim()
}

function Assert-CleanGit([string]$Root) {
    $status = Get-CommandOutput -FilePath "git" -Arguments @("status", "--porcelain") -WorkingDirectory $Root
    if ($status.Trim()) { throw "Working tree must be clean before building a release package." }
}

function Get-AppVersion([string]$Root, [string]$RequestedVersion) {
    if ($RequestedVersion.Trim()) { return $RequestedVersion.Trim() }
    $versionFile = Join-Path $Root "VERSION"
    if (-not (Test-Path -LiteralPath $versionFile)) { throw "VERSION file is missing." }
    $value = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    if (-not $value) { throw "VERSION file is empty." }
    return $value
}

function Assert-WindowsX64 {
    if ([Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) { throw "Portable package build is supported only on Windows." }
    if (-not [Environment]::Is64BitOperatingSystem) { throw "Portable package build requires Windows x64." }
}

function Assert-FreeSpace([string]$Path, [int64]$RequiredBytes) {
    $item = Get-Item -LiteralPath $Path
    $drive = Get-PSDrive -Name $item.PSDrive.Name
    if ($drive.Free -lt $RequiredBytes) {
        throw "Insufficient disk space on $($drive.Name): requires at least $([math]::Round($RequiredBytes / 1GB, 1)) GB free."
    }
}

function Copy-DirectoryContents([string]$Source, [string]$Destination, [string[]]$ExcludeNames = @()) {
    if (-not (Test-Path -LiteralPath $Source)) { throw "Source directory does not exist: $Source" }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        if ($ExcludeNames -contains $item.Name) { continue }
        $target = Join-Path $Destination $item.Name
        Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse -Force
    }
}

function Remove-GeneratedCaches([string]$Root) {
    foreach ($path in Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -ErrorAction SilentlyContinue) {
        if ($path.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")) {
            Remove-Item -LiteralPath $path.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-PythonScript([string]$Python, [string]$ScriptPath, [string[]]$Arguments, [string]$WorkingDirectory) {
    Run-Checked -FilePath $Python -Arguments (@($ScriptPath) + $Arguments) -WorkingDirectory $WorkingDirectory
}

function Write-Text([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Set-Content -LiteralPath $Path -Value $Text -Encoding UTF8
}

function Write-JsonFile([string]$Path, [object]$Value) {
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-CoreVersions([string]$Python, [string]$Root) {
    $code = @'
import importlib.metadata as m
import json
items = {}
for name in ["torch", "torch-geometric", "fastapi", "uvicorn"]:
    try:
        items[name] = m.version(name)
    except m.PackageNotFoundError:
        items[name] = None
try:
    import torch
    items["torch_cuda"] = getattr(torch.version, "cuda", None)
except Exception:
    items["torch_cuda"] = None
print(json.dumps(items, sort_keys=True))
'@
    $output = & $Python -c $code
    if ($LASTEXITCODE -ne 0) { throw "Could not read core package versions." }
    return ($output -join "") | ConvertFrom-Json
}

function Write-ValidationPayload([string]$Path) {
    $payload = @{
        sample_name = "portable-validation"
        inlet1 = 1.0
        inlet2 = 0.0
        chips = @(
            @{ position = 1; chip_type = "5to4"; left_width_mm = 1.1; right_width_mm = 1.2; left_bend_straight_distance_mm = 11.0; right_bend_straight_distance_mm = 21.0 },
            @{ position = 2; chip_type = "4to2"; left_width_mm = 2.1; right_width_mm = 2.2; left_bend_straight_distance_mm = 12.0; right_bend_straight_distance_mm = 22.0 },
            @{ position = 3; chip_type = "1to6"; left_width_mm = 3.1; right_width_mm = 3.2; left_bend_straight_distance_mm = 13.0; right_bend_straight_distance_mm = 23.0 },
            @{ position = 4; chip_type = "2to4"; left_width_mm = 4.1; right_width_mm = 4.2; left_bend_straight_distance_mm = 14.0; right_bend_straight_distance_mm = 24.0 },
            @{ position = 5; chip_type = "6to3"; left_width_mm = 5.1; right_width_mm = 5.2; left_bend_straight_distance_mm = 15.0; right_bend_straight_distance_mm = 25.0 },
            @{ position = 6; chip_type = "3to1"; left_width_mm = 6.1; right_width_mm = 6.2; left_bend_straight_distance_mm = 16.0; right_bend_straight_distance_mm = 26.0 }
        )
    }
    Write-JsonFile -Path $Path -Value $payload
}

function Invoke-FrontendBuild([string]$Root, [bool]$RunChecks) {
    $frontend = Join-Path $Root "frontend"
    $npm = Get-Command npm.cmd -ErrorAction Stop
    if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
        Run-Checked -FilePath $npm.Source -Arguments @("ci") -WorkingDirectory $frontend
    }
    if ($RunChecks) {
        Run-Checked -FilePath $npm.Source -Arguments @("run", "typecheck") -WorkingDirectory $frontend
        Run-Checked -FilePath $npm.Source -Arguments @("run", "lint") -WorkingDirectory $frontend
        Run-Checked -FilePath $npm.Source -Arguments @("run", "test:run") -WorkingDirectory $frontend
    }
    Run-Checked -FilePath $npm.Source -Arguments @("run", "build") -WorkingDirectory $frontend
}

function Invoke-HttpValidation([string]$Url, [string]$PayloadPath) {
    $health = Invoke-RestMethod -Method Get -Uri "$Url/api/v1/health" -TimeoutSec 10
    if ($health.status -ne "ok") { throw "Health endpoint returned an unexpected response." }
    $status = Invoke-RestMethod -Method Get -Uri "$Url/api/v1/model-status" -TimeoutSec 30
    if (-not $status.ready) { throw "Model status is not ready." }
    foreach ($path in @("/", "/forward", "/reverse")) {
        $response = Invoke-WebRequest -Method Get -Uri "$Url$path" -TimeoutSec 10 -UseBasicParsing
        if ($response.StatusCode -ne 200 -or $response.Content -notmatch "<!doctype html") {
            throw "Frontend route $path did not return the production app."
        }
    }
    $payload = Get-Content -LiteralPath $PayloadPath -Raw
    $forward = Invoke-RestMethod -Method Post -Uri "$Url/api/v1/forward" -ContentType "application/json" -Body $payload -TimeoutSec 60
    if ($forward.predictions.Count -ne 6) { throw "Forward endpoint did not return six predictions." }
}

function Invoke-PortableLifecycleValidation([string]$PackageRoot, [string]$PayloadPath, [int]$Port) {
    $hadModelSourceRoot = Test-Path Env:MODEL_SOURCE_ROOT
    $oldModelSourceRoot = if ($hadModelSourceRoot) { $env:MODEL_SOURCE_ROOT } else { $null }
    $oldPath = $env:Path
    $env:MODEL_SOURCE_ROOT = "Z:\portable-validation-should-be-ignored"
    $env:Path = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    try {
        $start = Join-Path $PackageRoot "start_app.cmd"
        $status = Join-Path $PackageRoot "status_app.cmd"
        $stop = Join-Path $PackageRoot "stop_app.cmd"
        Run-Checked -FilePath $start -Arguments @("-NoBrowser", "-Port", [string]$Port, "-StartupTimeoutSeconds", "180") -WorkingDirectory $PackageRoot
        Invoke-HttpValidation -Url "http://127.0.0.1:$Port" -PayloadPath $PayloadPath
        Run-Checked -FilePath $status -Arguments @() -WorkingDirectory $PackageRoot
        Run-Checked -FilePath $start -Arguments @("-NoBrowser", "-Port", [string]$Port) -WorkingDirectory $PackageRoot
        Run-Checked -FilePath $stop -Arguments @() -WorkingDirectory $PackageRoot
    } finally {
        $env:Path = $oldPath
        if ($hadModelSourceRoot) { $env:MODEL_SOURCE_ROOT = $oldModelSourceRoot } else { Remove-Item Env:MODEL_SOURCE_ROOT -ErrorAction SilentlyContinue }
        & (Join-Path $PackageRoot "stop_app.cmd") | Out-Null
    }
}

function Assert-NoDevPaths([string]$PackageRoot, [string[]]$ForbiddenFragments) {
    $extensions = @(".ps1", ".cmd", ".json", ".txt", ".html", ".js", ".css", ".py", ".pth", ".ini", ".cfg")
    foreach ($file in Get-ChildItem -LiteralPath $PackageRoot -Recurse -File -Force) {
        if ($extensions -notcontains $file.Extension.ToLowerInvariant()) { continue }
        $text = Get-Content -LiteralPath $file.FullName -Raw -ErrorAction SilentlyContinue
        foreach ($fragment in $ForbiddenFragments) {
            if ($fragment -and $text -like "*$fragment*") {
                throw "Portable text file contains development path fragment '$fragment': $($file.FullName)"
            }
        }
    }
}

function New-ZipArchive([string]$Python, [string]$SourceRoot, [string]$ZipPath, [string]$BuildRoot) {
    $script = Join-Path $BuildRoot "zip_portable.py"
    Write-Text -Path $script -Text @'
import pathlib
import sys
import zipfile

source = pathlib.Path(sys.argv[1]).resolve()
zip_path = pathlib.Path(sys.argv[2]).resolve()
top = source.name
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        archive.write(path, pathlib.PurePosixPath(top, path.relative_to(source).as_posix()).as_posix())
'@
    Invoke-PythonScript -Python $Python -ScriptPath $script -Arguments @($SourceRoot, $ZipPath) -WorkingDirectory $BuildRoot
}

try {
    $root = RepoRoot
    Assert-WindowsX64
    $appVersion = Get-AppVersion -Root $root -RequestedVersion $Version
    $output = if ($OutputRoot.Trim()) {
        if (-not (Test-Path -LiteralPath $OutputRoot)) { New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null }
        (Resolve-Path -LiteralPath $OutputRoot).Path
    } else {
        Join-Path $root "release"
    }
    $buildRoot = Join-Path $root ".build\portable"
    $packageName = "DrugGradientChip-$appVersion-Windows-x64"
    $stageRoot = Join-Path $buildRoot $packageName
    $runtimeArchive = Join-Path $buildRoot "drug-chip-runtime.tar.gz"
    $payloadPath = Join-Path $buildRoot "forward-payload.json"

    Assert-CleanGit -Root $root
    Assert-FreeSpace -Path $root -RequiredBytes (8GB)
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

    $appPython = Get-CondaPython -Name $CondaEnvironment
    $buildPython = Get-CondaPython -Name $BuildToolEnvironment
    $conda = Get-CondaCommand
    $commit = Get-CommandOutput -FilePath "git" -Arguments @("rev-parse", "HEAD") -WorkingDirectory $root
    $branch = Get-CommandOutput -FilePath "git" -Arguments @("branch", "--show-current") -WorkingDirectory $root
    $coreVersions = Get-CoreVersions -Python $appPython -Root $root
    $packVersion = Get-CommandOutput -FilePath $conda -Arguments @("list", "-n", $BuildToolEnvironment, "conda-pack") -WorkingDirectory $root

    if (-not $SkipTests) {
        Run-Checked -FilePath $appPython -Arguments @("-m", "pip", "check") -WorkingDirectory $root
        Run-Checked -FilePath $appPython -Arguments @("-m", "pytest", "-q", "--basetemp=.pytest_tmp") -WorkingDirectory $root
    }
    Invoke-FrontendBuild -Root $root -RunChecks:(-not $SkipTests)

    Run-Checked -FilePath "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\verify_forward_assets.ps1")) -WorkingDirectory $root

    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    foreach ($dir in @("backend\app", "model_assets\forward", "frontend\dist")) {
        Copy-DirectoryContents -Source (Join-Path $root $dir) -Destination (Join-Path $stageRoot $dir)
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $stageRoot "scripts") | Out-Null
    foreach ($script in @("start_local_app.ps1", "status_local_app.ps1", "stop_local_app.ps1", "verify_forward_assets.ps1")) {
        Copy-Item -LiteralPath (Join-Path $root "scripts\$script") -Destination (Join-Path $stageRoot "scripts\$script") -Force
    }
    foreach ($file in @("start_app.cmd", "status_app.cmd", "stop_app.cmd", "VERSION")) {
        Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $stageRoot $file) -Force
    }
    if (Test-Path -LiteralPath (Join-Path $root "backend\__init__.py")) {
        Copy-Item -LiteralPath (Join-Path $root "backend\__init__.py") -Destination (Join-Path $stageRoot "backend\__init__.py") -Force
    } else {
        Write-Text -Path (Join-Path $stageRoot "backend\__init__.py") -Text ""
    }
    Remove-GeneratedCaches -Root $stageRoot

    Info "Packing conda environment '$CondaEnvironment'."
    Run-Checked -FilePath $conda -Arguments @("run", "-n", $BuildToolEnvironment, "conda-pack", "-n", $CondaEnvironment, "-o", $runtimeArchive, "--force") -WorkingDirectory $root
    $extractScript = Join-Path $buildRoot "extract_runtime.py"
    Write-Text -Path $extractScript -Text @'
import pathlib
import sys
import tarfile

archive = pathlib.Path(sys.argv[1]).resolve()
target = pathlib.Path(sys.argv[2]).resolve()
target.mkdir(parents=True, exist_ok=True)
with tarfile.open(archive, "r:gz") as handle:
    handle.extractall(target)
'@
    Invoke-PythonScript -Python $buildPython -ScriptPath $extractScript -Arguments @($runtimeArchive, (Join-Path $stageRoot "runtime")) -WorkingDirectory $buildRoot

    $condaUnpack = Join-Path $stageRoot "runtime\Scripts\conda-unpack.exe"
    if (Test-Path -LiteralPath $condaUnpack) {
        Run-Checked -FilePath $condaUnpack -Arguments @() -WorkingDirectory $stageRoot
    } else {
        Warn "conda-unpack.exe was not found; continuing only if runtime validation succeeds."
    }

    $runtimePython = Join-Path $stageRoot "runtime\python.exe"
    Run-Checked -FilePath $runtimePython -Arguments @("--version") -WorkingDirectory $stageRoot
    $runtimePackages = Get-CommandOutput -FilePath $runtimePython -Arguments @("-m", "pip", "freeze") -WorkingDirectory $stageRoot
    Write-Text -Path (Join-Path $stageRoot "runtime-packages.txt") -Text $runtimePackages

    $buildInfo = [ordered]@{
        schema_version = 1
        app_name = "drug-gradient-chip"
        version = $appVersion
        build_commit = $commit
        source_branch = $branch
        build_time_utc = (Get-Date).ToUniversalTime().ToString("o")
        platform = "Windows-x64"
        runtime_mode = "portable"
        python_runtime = "conda-pack"
        source_conda_environment = $CondaEnvironment
        build_tool_environment = $BuildToolEnvironment
        conda_pack = ($packVersion -split "`n" | Where-Object { $_ -match "^conda-pack\s+" } | Select-Object -First 1)
        default_device = "cpu"
        torch_version = $coreVersions.torch
        torch_cuda_build = $coreVersions.torch_cuda
        torch_geometric_version = $coreVersions."torch-geometric"
        fastapi_version = $coreVersions.fastapi
        uvicorn_version = $coreVersions.uvicorn
    }
    Write-JsonFile -Path (Join-Path $stageRoot "BUILD_INFO.json") -Value $buildInfo
    Write-Text -Path (Join-Path $stageRoot "README.txt") -Text @"
Drug Gradient Chip - Windows Portable Package

Version: $appVersion
Build commit: $commit

Run:
  start_app.cmd

Status:
  status_app.cmd

Stop:
  stop_app.cmd

This package contains its own Python runtime and bundled forward model assets.
End users do not need Conda, Python, Node.js, npm, or the original model repository.
Portable mode always uses bundled assets and CPU by default.
"@

    Run-Checked -FilePath "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $stageRoot "scripts\verify_forward_assets.ps1")) -WorkingDirectory $stageRoot
    Assert-NoDevPaths -PackageRoot $stageRoot -ForbiddenFragments @($root, (Get-CondaEnvPath -Name $CondaEnvironment), "D:\pytorch_geometric-master")
    Write-ValidationPayload -Path $payloadPath
    Invoke-PortableLifecycleValidation -PackageRoot $stageRoot -PayloadPath $payloadPath -Port 8000

    $relocatedRoot = Join-Path $buildRoot "relocation test\Drug Gradient Chip 药物芯片"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $relocatedRoot) | Out-Null
    Copy-Item -LiteralPath $stageRoot -Destination $relocatedRoot -Recurse -Force
    Invoke-PortableLifecycleValidation -PackageRoot $relocatedRoot -PayloadPath $payloadPath -Port 8000

    if (-not $NoArchive) {
        $zipPath = Join-Path $output "$packageName.zip"
        if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
        New-ZipArchive -Python $buildPython -SourceRoot $stageRoot -ZipPath $zipPath -BuildRoot $buildRoot
        $sha = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Text -Path "$zipPath.sha256" -Text "$sha  $(Split-Path -Leaf $zipPath)"

        $extractRoot = Join-Path $buildRoot "zip extract"
        New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
        $unzipScript = Join-Path $buildRoot "unzip_portable.py"
        Write-Text -Path $unzipScript -Text @'
import pathlib
import sys
import zipfile

zip_path = pathlib.Path(sys.argv[1]).resolve()
target = pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(zip_path) as archive:
    archive.extractall(target)
'@
        Invoke-PythonScript -Python $buildPython -ScriptPath $unzipScript -Arguments @($zipPath, $extractRoot) -WorkingDirectory $buildRoot
        Invoke-PortableLifecycleValidation -PackageRoot (Join-Path $extractRoot $packageName) -PayloadPath $payloadPath -Port 8000
        Info "Created $zipPath"
        Info "Created $zipPath.sha256"
    }

    if (-not $KeepStaging) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Info "Portable package build completed."
    exit 0
} catch {
    Fail $_.Exception.Message
    exit 1
}
