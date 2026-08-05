[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$SourceCommit = "",
    [string]$ProductFeatureBaseline = "",
    [string]$OutputRoot = "",
    [string]$CondaEnvironment = "drug-chip",
    [string]$RuntimeCondaEnvironment = "",
    [ValidateSet("CUDA", "CPU")]
    [string]$DistributionFlavor = "CUDA",
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
function Quote-ProcessArgument([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Run-Checked([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [hashtable]$Environment = @{}) {
    $previous = @{}
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
    }
    try {
        $extension = [System.IO.Path]::GetExtension($FilePath)
        $display = "$FilePath $($Arguments -join ' ')"
        Info $display
        if ($extension -ieq ".cmd" -or $extension -ieq ".bat") {
            Push-Location -LiteralPath $WorkingDirectory
            try {
                & $FilePath @Arguments
                $exitCode = $LASTEXITCODE
            } finally {
                Pop-Location
            }
            if ($exitCode -ne 0) { throw "Command failed with exit code ${exitCode}: $display" }
        } elseif ($Arguments.Count -eq 0) {
            $process = Start-Process -FilePath $FilePath -WorkingDirectory $WorkingDirectory -Wait -PassThru -NoNewWindow
        } else {
            $nativeArguments = @($Arguments | ForEach-Object { Quote-ProcessArgument -Value $_ })
            $process = Start-Process -FilePath $FilePath -ArgumentList $nativeArguments -WorkingDirectory $WorkingDirectory -Wait -PassThru -NoNewWindow
            if ($process.ExitCode -ne 0) { throw "Command failed with exit code $($process.ExitCode): $display" }
        }
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
    $drive = [System.IO.DriveInfo]::new($item.PSDrive.Root)
    if ($drive.AvailableFreeSpace -lt $RequiredBytes) {
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

function ConvertTo-PythonCharExpression([string]$Value) {
    $codes = [int[]][char[]]$Value
    return "''.join(chr(c) for c in ($($codes -join ', '),))"
}

function Protect-CondaUnpackPlaceholderText([string]$Root) {
    foreach ($unpackScript in Get-ChildItem -LiteralPath $Root -Recurse -Force -File -Filter "conda-unpack-script.py" -ErrorAction SilentlyContinue) {
        $text = Get-Content -LiteralPath $unpackScript.FullName -Raw
        $matches = [regex]::Matches($text, "'[A-Za-z]:[\\/][^']+'")
        if ($matches.Count -eq 0) { continue }

        $replacements = [ordered]@{}
        foreach ($match in $matches) {
            if ($replacements.Contains($match.Value)) { continue }
            $literalValue = $match.Value.Substring(1, $match.Value.Length - 2).Replace("\\", "\")
            $variableName = "_portable_prefix_placeholder_$($replacements.Count)"
            $replacements[$match.Value] = $variableName
            $expression = ConvertTo-PythonCharExpression -Value $literalValue
            $text = $text -replace [regex]::Escape($match.Value), $variableName
            $definition = "$variableName = $expression`n"
            $text = $text -replace "_prefix_records = \[", "$definition`n_prefix_records = ["
        }
        Set-Content -LiteralPath $unpackScript.FullName -Value $text -Encoding UTF8
    }
}

function Remove-GeneratedCaches([string]$Root) {
    foreach ($unpackScript in Get-ChildItem -LiteralPath $Root -Recurse -Force -File -Filter "conda-unpack-script.py" -ErrorAction SilentlyContinue) {
        $lines = @(Get-Content -LiteralPath $unpackScript.FullName)
        $filtered = @(
            foreach ($line in $lines) {
                if ($line -match "__pycache__" -or $line -match "\.py[co]'" -or $line -match "\.log'" -or $line -match "\.pid'") { continue }
                if ($line -match "^\('conda-meta\\") { continue }
                $line
            }
        )
        if ($filtered.Count -ne $lines.Count) {
            Set-Content -LiteralPath $unpackScript.FullName -Value $filtered -Encoding UTF8
        }
    }
    Protect-CondaUnpackPlaceholderText -Root $Root
    foreach ($path in Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -ErrorAction SilentlyContinue) {
        if ($path.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".pytest_tmp")) {
            Remove-Item -LiteralPath $path.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "*.pyc" -or $_.Name -like "*.pyo" -or $_.Name -like "*.log" -or $_.Name -like "*.pid" } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
}

function Remove-ReleaseJunk([string]$PackageRoot) {
    Remove-GeneratedCaches -Root $PackageRoot
    foreach ($relative in @(
        ".runtime",
        ".git",
        ".pytest_cache",
        ".pytest_tmp",
        "backend\tests",
        "frontend\node_modules",
        "frontend\src",
        "frontend\coverage",
        "frontend\.vite",
        "runtime\conda-meta"
    )) {
        $path = Join-Path $PackageRoot $relative
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
        }
    }
    Remove-GeneratedCaches -Root $PackageRoot
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
    $script = Join-Path $env:TEMP "drug_chip_core_versions.py"
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
    Set-Content -LiteralPath $script -Value $code -Encoding UTF8
    try {
        $output = & $Python $script
        if ($LASTEXITCODE -ne 0) { throw "Could not read core package versions." }
        return ($output -join "") | ConvertFrom-Json
    } finally {
        Remove-Item -LiteralPath $script -Force -ErrorAction SilentlyContinue
    }
}

function Write-ValidationPayload([string]$Path) {
    $payload = @{
        sample_name = "portable-validation"
        chip_count = 6
        inlet1 = 1.0
        inlet2 = 0.0
        chips = @(
            @{ position = 1; chip_type = "5to4"; left_width_mm = 0.261; right_width_mm = 0.138; left_bend_straight_distance_mm = 31.0; right_bend_straight_distance_mm = 25.0 },
            @{ position = 2; chip_type = "4to2"; left_width_mm = 0.089; right_width_mm = 0.04; left_bend_straight_distance_mm = 25.0; right_bend_straight_distance_mm = 13.0 },
            @{ position = 3; chip_type = "1to6"; left_width_mm = 0.212; right_width_mm = 0.236; left_bend_straight_distance_mm = 7.0; right_bend_straight_distance_mm = 31.0 },
            @{ position = 4; chip_type = "2to4"; left_width_mm = 0.31; right_width_mm = 0.163; left_bend_straight_distance_mm = 13.0; right_bend_straight_distance_mm = 25.0 },
            @{ position = 5; chip_type = "6to3"; left_width_mm = 0.187; right_width_mm = 0.285; left_bend_straight_distance_mm = 37.0; right_bend_straight_distance_mm = 19.0 },
            @{ position = 6; chip_type = "3to1"; left_width_mm = 0.05; right_width_mm = 0.114; left_bend_straight_distance_mm = 13.0; right_bend_straight_distance_mm = 7.0 }
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

function Get-RuntimePackageAudit([string]$Python, [string]$WorkingDirectory) {
    $freeze = Get-CommandOutput -FilePath $Python -Arguments @("-m", "pip", "freeze") -WorkingDirectory $WorkingDirectory
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($freeze -split "`r?`n")) {
        if ($line -match "^\s*-e\s+") { continue }
        if ($line -match "^# Editable ") { continue }
        if ($line.Trim()) { $lines.Add($line) }
    }
    return ($lines -join [Environment]::NewLine)
}

function Remove-EditableAppInstall([string]$RuntimeRoot) {
    $sitePackages = Join-Path $RuntimeRoot "Lib\site-packages"
    $unpackScript = Join-Path $RuntimeRoot "Scripts\conda-unpack-script.py"
    $patterns = @(
        "__editable__.drug_gradient_chip_app-*.pth",
        "__editable___drug_gradient_chip_app_*.py",
        "drug_gradient_chip_app-*.dist-info"
    )

    if (Test-Path -LiteralPath $unpackScript) {
        $lines = @(Get-Content -LiteralPath $unpackScript)
        $filtered = @(
            foreach ($line in $lines) {
                if ($line -match "drug_gradient_chip_app" -or $line -match "__editable___drug_gradient_chip_app") { continue }
                $line
            }
        )
        if ($filtered.Count -ne $lines.Count) {
            Set-Content -LiteralPath $unpackScript -Value $filtered -Encoding UTF8
        }
    }

    if (Test-Path -LiteralPath $sitePackages) {
        foreach ($pattern in $patterns) {
            Get-ChildItem -LiteralPath $sitePackages -Force -Filter $pattern -ErrorAction SilentlyContinue |
                ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop }
        }
    }
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
    if ($forward.predictions.Count -ne 6) { throw "Forward endpoint did not return the expected validation predictions." }
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

function Invoke-PortableStart([string]$PackageRoot, [int]$Port) {
    Run-Checked -FilePath (Join-Path $PackageRoot "start_app.cmd") -Arguments @("-NoBrowser", "-Port", [string]$Port, "-StartupTimeoutSeconds", "180") -WorkingDirectory $PackageRoot
}

function Invoke-PortableStop([string]$PackageRoot) {
    Run-Checked -FilePath (Join-Path $PackageRoot "stop_app.cmd") -Arguments @() -WorkingDirectory $PackageRoot
}

function Assert-RuntimeMarker([string]$PackageRoot) {
    $marker = Join-Path $PackageRoot "runtime\.conda-unpacked"
    if (-not (Test-Path -LiteralPath $marker)) { throw "Portable runtime marker was not created: $marker" }
    $payload = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    $applicationRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
    $runtimeRoot = (Resolve-Path -LiteralPath (Join-Path $PackageRoot "runtime")).Path
    if ([string]$payload.application_root -ne $applicationRoot -or [string]$payload.runtime_root -ne $runtimeRoot) {
        throw "Portable runtime marker does not match this package root."
    }
}

function Invoke-PortableFirstAndSecondStartValidation([string]$PackageRoot, [string]$PayloadPath, [int]$Port) {
    $marker = Join-Path $PackageRoot "runtime\.conda-unpacked"
    if (Test-Path -LiteralPath $marker) { throw "Portable runtime marker exists before first start: $marker" }
    try {
        Invoke-PortableStart -PackageRoot $PackageRoot -Port $Port
        Assert-RuntimeMarker -PackageRoot $PackageRoot
        Invoke-HttpValidation -Url "http://127.0.0.1:$Port" -PayloadPath $PayloadPath
        Invoke-PortableStop -PackageRoot $PackageRoot

        $firstMarker = Get-Content -LiteralPath $marker -Raw
        Invoke-PortableStart -PackageRoot $PackageRoot -Port $Port
        $secondMarker = Get-Content -LiteralPath $marker -Raw
        if ($secondMarker -ne $firstMarker) { throw "Portable runtime marker changed on second start." }
        Invoke-HttpValidation -Url "http://127.0.0.1:$Port" -PayloadPath $PayloadPath
        Invoke-PortableStop -PackageRoot $PackageRoot
    } finally {
        & (Join-Path $PackageRoot "stop_app.cmd") | Out-Null
    }
}

function Assert-MovedInitializedPackageRefusesStart([string]$PackageRoot, [int]$Port) {
    $start = Join-Path $PackageRoot "start_app.cmd"
    Push-Location -LiteralPath $PackageRoot
    try {
        & $start -NoBrowser -Port $Port -StartupTimeoutSeconds 30
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
        & (Join-Path $PackageRoot "stop_app.cmd") | Out-Null
    }
    if ($exitCode -eq 0) { throw "Moved initialized portable package started successfully; expected refusal." }
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

function Assert-ReleaseTreeClean([string]$PackageRoot) {
    $bad = New-Object System.Collections.Generic.List[string]
    foreach ($item in Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force) {
        $relative = $item.FullName.Substring($PackageRoot.Length).TrimStart("\", "/")
        $parts = @($relative -split "[\\/]")
        if ($parts -contains ".runtime") { $bad.Add($relative); continue }
        if ($parts -contains ".git") { $bad.Add($relative); continue }
        if ($parts -contains "__pycache__") { $bad.Add($relative); continue }
        if ($parts -contains ".pytest_cache" -or $parts -contains ".pytest_tmp") { $bad.Add($relative); continue }
        if ($relative -like "backend\tests*" -or $relative -like "frontend\node_modules*" -or $relative -like "frontend\src*") { $bad.Add($relative); continue }
        if (-not $item.PSIsContainer -and ($item.Name -like "*.log" -or $item.Name -like "*.pid" -or $item.Name -like "*.pyc" -or $item.Name -eq "app-state.json" -or $item.Name -like ".env*")) {
            $bad.Add($relative)
        }
    }
    if ($bad.Count -gt 0) {
        $sample = (($bad | Select-Object -First 20) -join "; ")
        throw "Release package contains forbidden generated files: $sample"
    }
}

function New-ZipArchive([string]$Python, [string]$SourceRoot, [string]$ZipPath, [string]$BuildRoot, [string]$ReportPath) {
    $script = Join-Path $BuildRoot "zip_portable.py"
    Write-Text -Path $script -Text @'
import json
import pathlib
import sys
import zipfile

source = pathlib.Path(sys.argv[1]).resolve()
zip_path = pathlib.Path(sys.argv[2]).resolve()
report_path = pathlib.Path(sys.argv[3]).resolve()
top = source.name
forbidden_names = {".runtime", ".git", "__pycache__", ".pytest_cache", ".pytest_tmp", "node_modules"}
forbidden_suffixes = {".pyc", ".pyo", ".log", ".pid"}
entries = []
for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix().lower()):
    if path.is_dir():
        continue
    rel = path.relative_to(source)
    parts = set(rel.parts)
    if parts & forbidden_names:
        raise RuntimeError(f"forbidden generated directory in archive input: {rel.as_posix()}")
    if path.suffix.lower() in forbidden_suffixes or path.name == "app-state.json" or path.name.startswith(".env"):
        raise RuntimeError(f"forbidden generated file in archive input: {rel.as_posix()}")
    entries.append(path)

with zipfile.ZipFile(
    zip_path,
    "w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=9,
    allowZip64=True,
) as archive:
    for path in entries:
        if path.is_dir():
            continue
        archive.write(path, pathlib.PurePosixPath(top, path.relative_to(source).as_posix()).as_posix())

with zipfile.ZipFile(zip_path) as archive:
    bad = archive.testzip()
    if bad is not None:
        raise RuntimeError(f"zip test failed at {bad}")
    infos = archive.infolist()
    raw = sum(i.file_size for i in infos)
    compressed = sum(i.compress_size for i in infos)
    stored = sum(1 for i in infos if i.compress_type == zipfile.ZIP_STORED)
    deflated = sum(1 for i in infos if i.compress_type == zipfile.ZIP_DEFLATED)
    if infos and stored == len(infos):
        raise RuntimeError("all archive entries are ZIP_STORED")
    ordinary = [
        i for i in infos
        if pathlib.PurePosixPath(i.filename).suffix.lower() in {
            ".py", ".ps1", ".cmd", ".json", ".txt", ".html", ".js", ".css", ".csv", ".yml", ".yaml", ".md"
        }
    ]
    ordinary_deflated = sum(1 for i in ordinary if i.compress_type == zipfile.ZIP_DEFLATED)
    if ordinary and ordinary_deflated < max(1, int(len(ordinary) * 0.9)):
        raise RuntimeError("too many ordinary text files were not deflated")
    top_levels = {pathlib.PurePosixPath(i.filename).parts[0] for i in infos if pathlib.PurePosixPath(i.filename).parts}
    if len(top_levels) != 1:
        raise RuntimeError(f"archive must contain one top-level directory, found {sorted(top_levels)}")
    top_dirs = {}
    for i in infos:
        parts = pathlib.PurePosixPath(i.filename).parts
        key = parts[1] if len(parts) > 2 else (parts[1] if len(parts) > 1 else "")
        item = top_dirs.setdefault(key, {"raw_bytes": 0, "compressed_bytes": 0, "file_count": 0})
        item["raw_bytes"] += i.file_size
        item["compressed_bytes"] += i.compress_size
        item["file_count"] += 1
    largest = sorted(
        [{"path": i.filename, "raw_bytes": i.file_size, "compressed_bytes": i.compress_size, "compress_type": i.compress_type} for i in infos],
        key=lambda row: row["raw_bytes"],
        reverse=True,
    )[:30]
    report = {
        "archive": str(zip_path),
        "archive_size_bytes": zip_path.stat().st_size,
        "raw_bytes": raw,
        "compressed_bytes": compressed,
        "compression_ratio": (compressed / raw) if raw else None,
        "file_count": len(infos),
        "deflated_entries": deflated,
        "stored_entries": stored,
        "top_level_directories": sorted(top_levels),
        "top_directories": top_dirs,
        "largest_files": largest,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["archive_size_bytes", "raw_bytes", "compressed_bytes", "compression_ratio", "file_count", "deflated_entries", "stored_entries"]}, sort_keys=True))
'@
    Invoke-PythonScript -Python $Python -ScriptPath $script -Arguments @($SourceRoot, $ZipPath, $ReportPath) -WorkingDirectory $BuildRoot
}

function Expand-ZipArchiveWithPython([string]$Python, [string]$ZipPath, [string]$DestinationRoot, [string]$BuildRoot) {
    if (Test-Path -LiteralPath $DestinationRoot) { Remove-Item -LiteralPath $DestinationRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
    $script = Join-Path $BuildRoot "unzip_portable.py"
    Write-Text -Path $script -Text @'
import pathlib
import sys
import zipfile

zip_path = pathlib.Path(sys.argv[1]).resolve()
target = pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(zip_path) as archive:
    archive.extractall(target)
'@
    Invoke-PythonScript -Python $Python -ScriptPath $script -Arguments @($ZipPath, $DestinationRoot) -WorkingDirectory $BuildRoot
}

try {
    $root = RepoRoot
    Assert-WindowsX64
    $appVersion = Get-AppVersion -Root $root -RequestedVersion $Version
    $runtimeEnvironment = if ($RuntimeCondaEnvironment.Trim()) { $RuntimeCondaEnvironment.Trim() } else { $CondaEnvironment.Trim() }
    $flavorLower = $DistributionFlavor.ToLowerInvariant()
    $output = if ($OutputRoot.Trim()) {
        if (-not (Test-Path -LiteralPath $OutputRoot)) { New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null }
        (Resolve-Path -LiteralPath $OutputRoot).Path
    } else {
        Join-Path $root "release"
    }
    $buildRoot = Join-Path $root ".build\portable"
    $packageSuffix = if ($DistributionFlavor -eq "CPU") { "-CPU" } else { "" }
    $packageName = "DrugGradientChip-$appVersion-Windows-x64$packageSuffix"
    $stageRoot = Join-Path $buildRoot $packageName
    $runtimeArchive = Join-Path $buildRoot "$runtimeEnvironment-runtime.tar.gz"
    $payloadPath = Join-Path $buildRoot "forward-payload.json"
    $reportRoot = Join-Path $root ".build\reports"
    $sizeReportPath = Join-Path $reportRoot "$packageName-size-report.json"

    Assert-CleanGit -Root $root
    Assert-FreeSpace -Path $root -RequiredBytes (8GB)
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

    $appPython = Get-CondaPython -Name $runtimeEnvironment
    $buildPython = Get-CondaPython -Name $BuildToolEnvironment
    $conda = Get-CondaCommand
    $commit = Get-CommandOutput -FilePath "git" -Arguments @("rev-parse", "HEAD") -WorkingDirectory $root
    $sourceCommitForPackage = if ($SourceCommit.Trim()) { $SourceCommit.Trim() } else { $commit }
    $featureBaselineForPackage = $ProductFeatureBaseline.Trim()
    $branch = Get-CommandOutput -FilePath "git" -Arguments @("branch", "--show-current") -WorkingDirectory $root
    $coreVersions = Get-CoreVersions -Python $appPython -Root $root
    $packVersion = Get-CommandOutput -FilePath $conda -Arguments @("list", "-n", $BuildToolEnvironment, "conda-pack") -WorkingDirectory $root
    $assetManifest = Get-Content -LiteralPath (Join-Path $root "model_assets\physics_gnn\manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $checkpointSha = [string]$assetManifest.checkpoint_sha256
    if ($DistributionFlavor -eq "CPU" -and -not [string]::IsNullOrWhiteSpace([string]$coreVersions.torch_cuda)) {
        throw "CPU portable package requires a CPU-only torch build; found torch.version.cuda=$($coreVersions.torch_cuda)."
    }

    if (-not $SkipTests) {
        Run-Checked -FilePath $appPython -Arguments @("-m", "pip", "check") -WorkingDirectory $root
        Run-Checked -FilePath $appPython -Arguments @("-m", "pytest", "-q", "--basetemp=.pytest_tmp") -WorkingDirectory $root
    }
    Invoke-FrontendBuild -Root $root -RunChecks:(-not $SkipTests)

    Run-Checked -FilePath "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\verify_forward_assets.ps1"), "-PythonPath", $appPython) -WorkingDirectory $root

    New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
    foreach ($dir in @("backend\app", "model_assets\physics_gnn", "frontend\dist")) {
        Copy-DirectoryContents -Source (Join-Path $root $dir) -Destination (Join-Path $stageRoot $dir)
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $stageRoot "scripts") | Out-Null
    foreach ($script in @("local_app_lifecycle.ps1", "start_local_app.ps1", "status_local_app.ps1", "stop_local_app.ps1", "verify_forward_assets.ps1")) {
        Copy-Item -LiteralPath (Join-Path $root "scripts\$script") -Destination (Join-Path $stageRoot "scripts\$script") -Force
    }
    foreach ($file in @("start_app.cmd", "status_app.cmd", "stop_app.cmd")) {
        Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $stageRoot $file) -Force
    }
    Write-Text -Path (Join-Path $stageRoot "VERSION") -Text $appVersion
    if (Test-Path -LiteralPath (Join-Path $root "backend\__init__.py")) {
        Copy-Item -LiteralPath (Join-Path $root "backend\__init__.py") -Destination (Join-Path $stageRoot "backend\__init__.py") -Force
    } else {
        Write-Text -Path (Join-Path $stageRoot "backend\__init__.py") -Text ""
    }
    Remove-GeneratedCaches -Root $stageRoot

    Info "Packing conda environment '$runtimeEnvironment'."
    Run-Checked -FilePath $conda -Arguments @("run", "-n", $BuildToolEnvironment, "conda-pack", "-n", $runtimeEnvironment, "-o", $runtimeArchive, "--force", "--ignore-editable-packages") -WorkingDirectory $root
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

    $runtimePython = Join-Path $stageRoot "runtime\python.exe"
    if (-not (Test-Path -LiteralPath $runtimePython)) { throw "Portable runtime python.exe was not extracted." }
    if (-not (Test-Path -LiteralPath (Join-Path $stageRoot "runtime\Scripts\conda-unpack.exe"))) {
        throw "Portable runtime conda-unpack.exe was not extracted."
    }
    Remove-EditableAppInstall -RuntimeRoot (Join-Path $stageRoot "runtime")
    $runtimePackages = Get-RuntimePackageAudit -Python $appPython -WorkingDirectory $root
    Write-Text -Path (Join-Path $stageRoot "runtime-packages.txt") -Text $runtimePackages

    $buildInfo = [ordered]@{
        schema_version = 1
        app_name = "drug-gradient-chip"
        product = "Drug Concentration Gradient Chip Prediction System"
        chinese_name = "药物浓度梯度芯片预测系统"
        version = $appVersion
        release_channel = "internal-test"
        release_stage = "Release Candidate"
        production_release = $false
        git_commit = $sourceCommitForPackage
        source_commit = $sourceCommitForPackage
        product_feature_baseline = $featureBaselineForPackage
        build_commit = $sourceCommitForPackage
        builder_commit = $commit
        source_branch = $branch
        build_time_utc = (Get-Date).ToUniversalTime().ToString("o")
        platform = "Windows-x64"
        distribution_flavor = $flavorLower
        runtime_mode = "portable"
        python_runtime = "conda-pack"
        source_conda_environment = $runtimeEnvironment
        build_tool_environment = $BuildToolEnvironment
        conda_pack = ($packVersion -split "`n" | Where-Object { $_ -match "^conda-pack\s+" } | Select-Object -First 1)
        default_device = "cpu"
        inference_device_default = "cpu"
        runtime_contains_cuda_build = ($null -ne $coreVersions.torch_cuda)
        torch_version = $coreVersions.torch
        torch_cuda_build = $coreVersions.torch_cuda
        torch_geometric_version = $coreVersions."torch-geometric"
        fastapi_version = $coreVersions.fastapi
        uvicorn_version = $coreVersions.uvicorn
        model = "PhysicsGuidedDualTaskGNN"
        model_seed = 44
        checkpoint_file = "best_concentration_checkpoint.pt"
        checkpoint_sha256 = $checkpointSha
        forward_supported_chip_counts = @(4, 5, 6, 7, 8, 9, 10)
        forward_configurable_chip_counts = @(4, 5, 6, 7, 8, 9, 10)
        reverse_supported_chip_counts = @(6)
        interface_languages = @("zh-CN", "en")
        internal_test_notice = "This is an internal test build and is not a production release."
    }
    Write-JsonFile -Path (Join-Path $stageRoot "BUILD_INFO.json") -Value $buildInfo
    Write-Text -Path (Join-Path $stageRoot "TEST_BUILD_INFO.txt") -Text @"
Product: Drug Concentration Gradient Chip Prediction System
Chinese name: 药物浓度梯度芯片预测系统
Version: $appVersion
Release channel: internal-test
Release stage: Release Candidate
Production release: no
Notice: This is an internal test build and is not a production release.
Source branch: $branch
Source commit: $sourceCommitForPackage
Product feature baseline: $featureBaselineForPackage
Builder commit: $commit
Platform: Windows x64
Runtime: CPU-only
Model: PhysicsGuidedDualTaskGNN
Model seed: 44
Checkpoint file: best_concentration_checkpoint.pt
Checkpoint SHA256: $checkpointSha
Build timestamp UTC: $($buildInfo.build_time_utc)
Builder script: scripts/build_portable_package.ps1
Forward supported chip counts: [4,5,6,7,8,9,10]
Forward configurable chip counts: [4,5,6,7,8,9,10]
Reverse supported chip counts: [6]
Interface languages: [zh-CN,en]
Torch version: $($coreVersions.torch)
Torch CUDA build: $($coreVersions.torch_cuda)
Torch Geometric version: $($coreVersions."torch-geometric")
"@
    Write-Text -Path (Join-Path $stageRoot "README.txt") -Text @"
Drug Concentration Gradient Chip Prediction System
Version: $appVersion
Release channel: internal-test / Release Candidate

This is an internal test build and is not a production release.

中文说明
--------
此版本为内部测试版，不是正式发布版本。
默认界面语言为中文，可在右上角切换到 English/EN。
语言偏好保存在本地浏览器中，刷新后会保持。
正向预测 / Forward Prediction 支持 4～10 个芯片真实预测。
该 checkpoint 由六芯片数据训练，并通过 zero-shot scale extension 扩展到 4～10 个芯片。
正向宽度范围为 0.04 到 0.31 mm，宽度步长为 0.001 mm。
距离输入步长为 1 mm。
正向预测公共结果只显示浓度，不显示 flow、seed、mean 或 std。
反向预测 / Reverse Prediction 固定支持 6 个芯片。
反向预测通常需要几十秒，同一时间最多运行一个反向任务。
反向结果仅经过 Physics-GNN 代理模型内部筛选，最终结构仍需 Fluent/CFD 独立验证。
默认地址为 http://127.0.0.1:8000。
无需安装 Python、Conda、Node.js 或 npm，无需联网。
测试反馈请记录版本 $appVersion 和 commit ${sourceCommitForPackage}。

使用方法
--------
启动: start_app.cmd
状态: status_app.cmd
停止: stop_app.cmd

English
-------
This is an internal test build and is not a production release.
The default interface language is Chinese. Use the top-right language switcher to choose EN.
The language preference is stored in the local browser and survives refresh.
Forward Prediction supports real prediction for four to ten chips.
The checkpoint was trained on six-chip data and is used for zero-shot scale extension to four through ten chips.
Forward width range is 0.04 to 0.31 mm with a 0.001 mm step.
Distance inputs use a 1 mm step.
Forward public output contains concentration only; flow, seed, mean, and std are not shown.
Reverse Prediction supports fixed-six-chip asynchronous tasks.
Reverse Prediction usually takes tens of seconds, and only one reverse task can run at a time.
Reverse results are screened by the Physics-GNN surrogate model only; final structures still require independent Fluent/CFD verification.
Default URL: http://127.0.0.1:8000.
Python, Conda, Node.js, and npm are not required. Internet access is not required.

Portable runtime note
---------------------
On first start, the package relocates its runtime for the current directory.
Do not move a directory after it has been started. To migrate the app, extract the original ZIP again at the target location.
"@

    Run-Checked -FilePath "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $stageRoot "scripts\verify_forward_assets.ps1"), "-PythonPath", $appPython) -WorkingDirectory $stageRoot
    Remove-ReleaseJunk -PackageRoot $stageRoot
    Assert-ReleaseTreeClean -PackageRoot $stageRoot
    Assert-NoDevPaths -PackageRoot $stageRoot -ForbiddenFragments @($root, (Get-CondaEnvPath -Name $runtimeEnvironment), "D:\pytorch_geometric-master")
    Write-ValidationPayload -Path $payloadPath
    if (Test-Path -LiteralPath (Join-Path $stageRoot "runtime\.conda-unpacked")) {
        throw "Release source runtime must not contain a conda-unpack marker."
    }

    if (-not $NoArchive) {
        $zipPath = Join-Path $output "$packageName.zip"
        if (Test-Path -LiteralPath $zipPath) {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $zipPath = Join-Path $output "$packageName-$timestamp.zip"
            Warn "Requested ZIP already exists; writing timestamped test package instead: $(Split-Path -Leaf $zipPath)"
        }
        if ((Test-Path -LiteralPath $zipPath) -or (Test-Path -LiteralPath "$zipPath.sha256")) {
            throw "Refusing to overwrite existing portable package output: $zipPath"
        }
        New-ZipArchive -Python $buildPython -SourceRoot $stageRoot -ZipPath $zipPath -BuildRoot $buildRoot -ReportPath $sizeReportPath
        $sha = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Text -Path "$zipPath.sha256" -Text "$sha  $(Split-Path -Leaf $zipPath)"

        $extractRootA = Join-Path $buildRoot "path A"
        Expand-ZipArchiveWithPython -Python $buildPython -ZipPath $zipPath -DestinationRoot $extractRootA -BuildRoot $buildRoot
        $packageRootA = Join-Path $extractRootA $packageName
        Invoke-PortableFirstAndSecondStartValidation -PackageRoot $packageRootA -PayloadPath $payloadPath -Port 8000

        $chinesePathName = "Drug Gradient Chip " + [string][char]0x4e2d + [string][char]0x6587
        $extractRootB = Join-Path (Join-Path $buildRoot "path B with spaces") $chinesePathName
        Expand-ZipArchiveWithPython -Python $buildPython -ZipPath $zipPath -DestinationRoot $extractRootB -BuildRoot $buildRoot
        $packageRootB = Join-Path $extractRootB $packageName
        Invoke-PortableFirstAndSecondStartValidation -PackageRoot $packageRootB -PayloadPath $payloadPath -Port 8000

        $movedRootCParent = Join-Path $buildRoot "path C moved initialized"
        if (Test-Path -LiteralPath $movedRootCParent) { Remove-Item -LiteralPath $movedRootCParent -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $movedRootCParent | Out-Null
        $packageRootC = Join-Path $movedRootCParent $packageName
        Move-Item -LiteralPath $packageRootA -Destination $packageRootC
        Assert-MovedInitializedPackageRefusesStart -PackageRoot $packageRootC -Port 8000
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
