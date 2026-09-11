[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ProductDisplayName = '"\u667a\u80fd\u836f\u7269\u6d53\u5ea6\u9884\u6d4b\u5e73\u53f0"' | ConvertFrom-Json

function Write-PortableRuntimeInfo([string]$Message) { Write-Host "[info] $Message" }
function Write-PortableRuntimeWarn([string]$Message) { Write-Warning $Message }

function Get-PortableRuntimeReadyMarkerPath([string]$Root) {
    return Join-Path (Join-Path $Root "runtime") ".conda-unpacked"
}

function Get-PortableRuntimeLockPath([string]$Root) {
    return Join-Path (Join-Path $Root ".runtime") "conda-unpack.lock"
}

function Write-PortableRuntimeJsonAtomically([string]$Path, [object]$Value) {
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

function Invoke-PortableRuntimeProcessWithTimeout {
    param(
        [Parameter(Mandatory = $true)] [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [int]$TimeoutSeconds = 600,
        [string]$RedirectStandardOutput = "",
        [string]$RedirectStandardError = "",
        [switch]$NoNewWindow
    )
    if ($TimeoutSeconds -le 0) { throw "Process timeout must be positive." }
    $startParams = @{
        FilePath = $FilePath
        PassThru = $true
    }
    if ($null -ne $ArgumentList -and $ArgumentList.Count -gt 0) { $startParams["ArgumentList"] = $ArgumentList }
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

function Show-PortableRuntimeCondaUnpackLogTail([string]$StdoutLog, [string]$StderrLog) {
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
        Write-PortableRuntimeWarn "Could not read conda-unpack logs: $($_.Exception.Message)"
    }
}

function Remove-PortableRuntimeEditableAppInstall([string]$RuntimeRoot) {
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

function Test-PortableRuntimeMarker([string]$Root) {
    $runtimeRoot = (Resolve-Path -LiteralPath (Join-Path $Root "runtime")).Path
    $applicationRoot = (Resolve-Path -LiteralPath $Root).Path
    $marker = Get-PortableRuntimeReadyMarkerPath -Root $Root
    if (-not (Test-Path -LiteralPath $marker)) { return $false }
    $payload = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ([string]$payload.application_root -ne $applicationRoot -or [string]$payload.runtime_root -ne $runtimeRoot) {
        throw "Portable runtime was already initialized at a different path. Re-extract the original ZIP or reinstall to the target location instead of moving an initialized directory."
    }
    return $true
}

function Wait-PortableRuntimeMarker {
    param(
        [Parameter(Mandatory = $true)] [string]$Root,
        [Parameter(Mandatory = $true)] [int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-PortableRuntimeMarker -Root $Root) { return $true }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Invoke-PortableRuntimeWithLock {
    param(
        [Parameter(Mandatory = $true)] [string]$Root,
        [Parameter(Mandatory = $true)] [int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)] [scriptblock]$Body
    )
    $lockPath = Get-PortableRuntimeLockPath -Root $Root
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $lockPath) | Out-Null
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $stream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            try {
                return & $Body
            } finally {
                $stream.Dispose()
                Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
            }
        } catch [System.IO.IOException] {
            Write-PortableRuntimeInfo "Portable runtime initialization is already in progress; waiting for it to finish."
            if (Wait-PortableRuntimeMarker -Root $Root -TimeoutSeconds 2) { return }
        }
    } while ((Get-Date) -lt $deadline)
    throw "Portable runtime initialization is already in progress and did not finish within ${TimeoutSeconds}s."
}

function Ensure-PortableRuntimeReady {
    param(
        [Parameter(Mandatory = $true)] [string]$Root,
        [Parameter(Mandatory = $true)] [string]$LogsDir,
        [int]$TimeoutSeconds = 600
    )
    $runtimeRoot = (Resolve-Path -LiteralPath (Join-Path $Root "runtime")).Path
    $applicationRoot = (Resolve-Path -LiteralPath $Root).Path
    $marker = Get-PortableRuntimeReadyMarkerPath -Root $Root
    if (Test-PortableRuntimeMarker -Root $Root) {
        Write-PortableRuntimeInfo "Portable runtime is already relocated."
        return
    }

    Invoke-PortableRuntimeWithLock -Root $Root -TimeoutSeconds $TimeoutSeconds -Body {
        if (Test-PortableRuntimeMarker -Root $Root) {
            Write-PortableRuntimeInfo "Portable runtime is already relocated."
            return
        }
        $runtimePython = Join-Path $runtimeRoot "python.exe"
        $condaUnpackScript = Join-Path $runtimeRoot "Scripts\conda-unpack-script.py"
        if (-not (Test-Path -LiteralPath $runtimePython)) {
            throw "Portable runtime Python was not found: $runtimePython"
        }
        if (-not (Test-Path -LiteralPath $condaUnpackScript)) {
            throw "Portable runtime relocation script was not found: $condaUnpackScript"
        }
        $stdoutLog = Join-Path $LogsDir "conda-unpack.stdout.log"
        $stderrLog = Join-Path $LogsDir "conda-unpack.stderr.log"
        $quotedCondaUnpackScript = "`"$condaUnpackScript`""
        Write-PortableRuntimeInfo "$ProductDisplayName is preparing its local runtime for first use. This may take several minutes."
        Write-PortableRuntimeInfo "Relocating portable runtime for this directory."
        $process = Invoke-PortableRuntimeProcessWithTimeout -FilePath $runtimePython -ArgumentList @($quotedCondaUnpackScript) -WorkingDirectory $Root -TimeoutSeconds $TimeoutSeconds -NoNewWindow -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        if ($process.ExitCode -ne 0) {
            Show-PortableRuntimeCondaUnpackLogTail -StdoutLog $stdoutLog -StderrLog $stderrLog
            throw "Portable runtime relocation failed with exit code $($process.ExitCode)."
        }
        Remove-PortableRuntimeEditableAppInstall -RuntimeRoot $runtimeRoot
        Write-PortableRuntimeJsonAtomically -Path $marker -Value ([ordered]@{
            schema_version = 1
            application_root = $applicationRoot
            runtime_root = $runtimeRoot
            completed_at = (Get-Date).ToUniversalTime().ToString("o")
        })
        Write-PortableRuntimeInfo "Portable runtime relocation completed."
    }
}
