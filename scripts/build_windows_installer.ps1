[CmdletBinding()]
param(
    [string]$Version = "0.3.0-rc7",
    [string]$SourceCommit = "",
    [string]$ProductFeatureBaseline = "",
    [string]$OutputRoot = "",
    [string]$RuntimeCondaEnvironment = "drug-chip-portable-cpu",
    [string]$BuildToolEnvironment = "drug-chip-portable-build",
    [switch]$SkipPortableTests,
    [switch]$KeepStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Info([string]$Message) { Write-Host "[info] $Message" }
function Fail([string]$Message) { Write-Host "[error] $Message" }
function RepoRoot { return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
function Write-Text([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Set-Content -LiteralPath $Path -Value $Text -Encoding UTF8
}
function Get-CommandOutput([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    $output = & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $FilePath $($Arguments -join ' ')" }
    return ($output -join [Environment]::NewLine).Trim()
}
function Resolve-Iscc {
    if ($env:ISCC_PATH -and $env:ISCC_PATH.Trim()) {
        if (-not (Test-Path -LiteralPath $env:ISCC_PATH)) { throw "ISCC_PATH does not point to an existing file: $env:ISCC_PATH" }
        return (Resolve-Path -LiteralPath $env:ISCC_PATH).Path
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw "ISCC.exe was not found. Set ISCC_PATH, add ISCC.exe to PATH, or install Inno Setup 6."
}
function Resolve-WebView2Installer {
    if (-not $env:WEBVIEW2_INSTALLER_PATH -or -not $env:WEBVIEW2_INSTALLER_PATH.Trim()) {
        throw "WEBVIEW2_INSTALLER_PATH must point to the official Microsoft Edge WebView2 x64 Evergreen Standalone Installer."
    }
    $path = (Resolve-Path -LiteralPath $env:WEBVIEW2_INSTALLER_PATH).Path
    $item = Get-Item -LiteralPath $path
    if ($item.Name -notmatch "X64|x64") {
        throw "WebView2 installer file name must indicate x64 architecture: $path"
    }
    if ($item.Length -lt 100MB) {
        throw "WebView2 installer is too small for the Evergreen Standalone Installer and is likely a bootstrapper: $path"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne "Valid") {
        throw "WebView2 installer signature is not valid: $($signature.Status)"
    }
    if ($null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch "Microsoft Corporation") {
        throw "WebView2 installer is not signed by Microsoft Corporation."
    }
    $version = (Get-Item -LiteralPath $path).VersionInfo
    $sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Info "WebView2 installer: $path"
    Info "WebView2 installer size: $($item.Length)"
    Info "WebView2 installer SHA256: $sha"
    Info "WebView2 installer version: $($version.FileVersion)"
    return [pscustomobject]@{
        Path = $path
        Size = $item.Length
        Sha256 = $sha
        FileVersion = $version.FileVersion
        ProductVersion = $version.ProductVersion
    }
}
function New-AppIcon([string]$Path) {
    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new(64, 64)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.Clear([System.Drawing.Color]::FromArgb(25, 39, 52))
        $brushA = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(39, 174, 96))
        $brushB = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(52, 152, 219))
        $pen = [System.Drawing.Pen]::new([System.Drawing.Color]::White, 4)
        $graphics.FillRectangle($brushA, 10, 12, 18, 40)
        $graphics.FillRectangle($brushB, 36, 12, 18, 40)
        $graphics.DrawLine($pen, 28, 20, 36, 20)
        $graphics.DrawLine($pen, 28, 44, 36, 44)
        $graphics.DrawEllipse($pen, 8, 10, 48, 44)
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
        $icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
        $stream = [System.IO.File]::Create($Path)
        try { $icon.Save($stream) } finally { $stream.Dispose(); $icon.Dispose() }
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}
function Invoke-Checked([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    Info "$FilePath $($Arguments -join ' ')"
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($exitCode -ne 0) { throw "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')" }
}
function New-ZipArchive([string]$SourceRoot, [string]$ZipPath, [string]$TopLevelName) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ZipPath) { throw "Refusing to overwrite existing ZIP: $ZipPath" }
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("drug-chip-installer-zip-" + [guid]::NewGuid().ToString("N"))
    try {
        $top = Join-Path $tempRoot $TopLevelName
        New-Item -ItemType Directory -Force -Path $top | Out-Null
        foreach ($item in Get-ChildItem -LiteralPath $SourceRoot -Force) {
            Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $top $item.Name) -Recurse -Force
        }
        [System.IO.Compression.ZipFile]::CreateFromDirectory($top, $ZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    $root = RepoRoot
    $output = if ($OutputRoot.Trim()) {
        if (-not (Test-Path -LiteralPath $OutputRoot)) { New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null }
        (Resolve-Path -LiteralPath $OutputRoot).Path
    } else {
        Join-Path $root "release\test"
    }
    New-Item -ItemType Directory -Force -Path $output | Out-Null

    $iscc = Resolve-Iscc
    $webView2Installer = Resolve-WebView2Installer
    $commit = Get-CommandOutput -FilePath "git" -Arguments @("rev-parse", "HEAD") -WorkingDirectory $root
    $sourceCommitForPackage = if ($SourceCommit.Trim()) { $SourceCommit.Trim() } else { $commit }
    $featureBaselineForPackage = if ($ProductFeatureBaseline.Trim()) { $ProductFeatureBaseline.Trim() } else { $sourceCommitForPackage }
    $branch = Get-CommandOutput -FilePath "git" -Arguments @("branch", "--show-current") -WorkingDirectory $root
    $buildRoot = Join-Path $root ".build\installer"
    $stagePackageName = "DrugGradientChip-$Version-Windows-x64-CPU"
    $portableName = "DrugGradientChip-$Version-Windows-x64-CPU-Portable"
    $stageRoot = Join-Path $root ".build\portable\$stagePackageName"
    $portableZip = Join-Path $output "$portableName.zip"
    $setupExe = Join-Path $output "DrugGradientChip-Setup-$Version-Windows-x64.exe"
    if (Test-Path -LiteralPath $portableZip) { throw "Refusing to overwrite existing portable ZIP: $portableZip" }
    if (Test-Path -LiteralPath "$portableZip.sha256") { throw "Refusing to overwrite existing portable ZIP checksum: $portableZip.sha256" }
    if (Test-Path -LiteralPath $setupExe) { throw "Refusing to overwrite existing setup executable: $setupExe" }
    if (Test-Path -LiteralPath "$setupExe.sha256") { throw "Refusing to overwrite existing setup checksum: $setupExe.sha256" }

    if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

    $portableArgs = @(
        "-Version", $Version,
        "-SourceCommit", $sourceCommitForPackage,
        "-ProductFeatureBaseline", $featureBaselineForPackage,
        "-OutputRoot", $output,
        "-RuntimeCondaEnvironment", $RuntimeCondaEnvironment,
        "-DistributionFlavor", "CPU",
        "-BuildToolEnvironment", $BuildToolEnvironment,
        "-NoArchive",
        "-KeepStaging",
        "-AllowDirty"
    )
    if ($SkipPortableTests) { $portableArgs += "-SkipTests" }
    $portableCommandArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $root "scripts\build_portable_package.ps1")) + $portableArgs
    Invoke-Checked -FilePath "powershell.exe" -Arguments $portableCommandArgs -WorkingDirectory $root
    if (-not (Test-Path -LiteralPath $stageRoot)) { throw "Portable stage was not created: $stageRoot" }

    $resources = Join-Path $stageRoot "resources"
    New-Item -ItemType Directory -Force -Path $resources | Out-Null
    Copy-Item -LiteralPath (Join-Path $root "launcher.pyw") -Destination (Join-Path $stageRoot "launcher.pyw") -Force
    Copy-Item -LiteralPath (Join-Path $root "stopper.pyw") -Destination (Join-Path $stageRoot "stopper.pyw") -Force
    Copy-Item -LiteralPath (Join-Path $root "desktop_shell.py") -Destination (Join-Path $stageRoot "desktop_shell.py") -Force
    $iconPath = Join-Path $resources "drug-gradient-chip.ico"
    New-AppIcon -Path $iconPath

    $buildInfoPath = Join-Path $stageRoot "BUILD_INFO.json"
    $buildInfo = Get-Content -LiteralPath $buildInfoPath -Raw | ConvertFrom-Json
    $buildInfo | Add-Member -NotePropertyName installer_version -NotePropertyValue $Version -Force
    $buildInfo | Add-Member -NotePropertyName source_branch -NotePropertyValue $branch -Force
    $buildInfo | Add-Member -NotePropertyName source_commit -NotePropertyValue $sourceCommitForPackage -Force
    $buildInfo | Add-Member -NotePropertyName product_feature_baseline -NotePropertyValue $featureBaselineForPackage -Force
    $buildInfo | Add-Member -NotePropertyName builder_commit -NotePropertyValue $commit -Force
    $buildInfo | Add-Member -NotePropertyName windows_installer -NotePropertyValue $true -Force
    $buildInfo | Add-Member -NotePropertyName webview2_installer_embedded -NotePropertyValue $true -Force
    $buildInfo | Add-Member -NotePropertyName webview2_installer_size -NotePropertyValue $webView2Installer.Size -Force
    $buildInfo | Add-Member -NotePropertyName webview2_installer_sha256 -NotePropertyValue $webView2Installer.Sha256 -Force
    $buildInfo | Add-Member -NotePropertyName webview2_installer_file_version -NotePropertyValue $webView2Installer.FileVersion -Force
    $buildInfo | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $buildInfoPath -Encoding UTF8
    Add-Content -LiteralPath (Join-Path $stageRoot "TEST_BUILD_INFO.txt") -Encoding UTF8 -Value @"
Installer: DrugGradientChip-Setup-$Version-Windows-x64.exe
Installer builder script: scripts/build_windows_installer.ps1
Source branch: $branch
Source commit: $sourceCommitForPackage
Product feature baseline: $featureBaselineForPackage
Builder commit: $commit
WebView2 installer embedded: yes
WebView2 installer size: $($webView2Installer.Size)
WebView2 installer SHA256: $($webView2Installer.Sha256)
WebView2 installer file version: $($webView2Installer.FileVersion)
"@

    New-ZipArchive -SourceRoot $stageRoot -ZipPath $portableZip -TopLevelName $portableName
    $portableSha = (Get-FileHash -LiteralPath $portableZip -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Text -Path "$portableZip.sha256" -Text "$portableSha  $(Split-Path -Leaf $portableZip)"

    $env:DGC_APP_VERSION = $Version
    $env:DGC_PACKAGE_ROOT = $stageRoot
    $env:DGC_OUTPUT_DIR = $output
    $env:DGC_OUTPUT_BASE_FILENAME = "DrugGradientChip-Setup-$Version-Windows-x64"
    $env:DGC_APP_ICON = $iconPath
    $env:DGC_WEBVIEW2_INSTALLER = $webView2Installer.Path
    try {
        Invoke-Checked -FilePath $iscc -Arguments @((Join-Path $root "installer\windows\DrugGradientChip.iss")) -WorkingDirectory $root
    } finally {
        foreach ($name in "DGC_APP_VERSION", "DGC_PACKAGE_ROOT", "DGC_OUTPUT_DIR", "DGC_OUTPUT_BASE_FILENAME", "DGC_APP_ICON", "DGC_WEBVIEW2_INSTALLER") {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path -LiteralPath $setupExe)) { throw "Setup executable was not created: $setupExe" }
    $setupSha = (Get-FileHash -LiteralPath $setupExe -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Text -Path "$setupExe.sha256" -Text "$setupSha  $(Split-Path -Leaf $setupExe)"

    Info "Source branch: $branch"
    Info "Source commit: $sourceCommitForPackage"
    Info "Product feature baseline: $featureBaselineForPackage"
    Info "Builder commit: $commit"
    Info "Created portable ZIP: $portableZip"
    Info "Portable SHA256: $portableSha"
    Info "Created setup EXE: $setupExe"
    Info "Setup SHA256: $setupSha"
    if (-not $KeepStaging) {
        Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $root ".build\portable") -Recurse -Force -ErrorAction SilentlyContinue
    }
    exit 0
} catch {
    Fail $_.Exception.Message
    exit 1
}
