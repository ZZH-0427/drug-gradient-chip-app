[CmdletBinding()]
param()

Set-StrictMode -Version Latest

$script:AppModule = "backend.app.main:app"

function Get-LocalAppRepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-LocalAppStatePath([string]$Root) {
    return Join-Path (Join-Path $Root ".runtime") "app-state.json"
}

function ConvertTo-LocalAppNormalizedPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    $full = [System.IO.Path]::GetFullPath($Path)
    return $full.TrimEnd('\', '/').Replace('/', '\')
}

function Test-LocalAppPathEqual([string]$Left, [string]$Right) {
    $normalizedLeft = ConvertTo-LocalAppNormalizedPath -Path $Left
    $normalizedRight = ConvertTo-LocalAppNormalizedPath -Path $Right
    return [string]::Equals($normalizedLeft, $normalizedRight, [System.StringComparison]::OrdinalIgnoreCase)
}

function ConvertTo-LocalAppUtcIso([object]$Value) {
    if ($null -eq $Value) { return "" }
    if ($Value -is [datetime]) {
        return $Value.ToUniversalTime().ToString("o")
    }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return "" }
    try {
        if ($text -match '^\d{14}\.') {
            return ([System.Management.ManagementDateTimeConverter]::ToDateTime($text)).ToUniversalTime().ToString("o")
        }
        return ([datetime]::Parse($text, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal)).ToUniversalTime().ToString("o")
    } catch {
        return ""
    }
}

function Test-LocalAppTimeClose([string]$LeftUtcIso, [string]$RightUtcIso, [int]$ToleranceSeconds = 2) {
    if ([string]::IsNullOrWhiteSpace($LeftUtcIso) -or [string]::IsNullOrWhiteSpace($RightUtcIso)) { return $false }
    try {
        $left = [datetime]::Parse($LeftUtcIso, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal).ToUniversalTime()
        $right = [datetime]::Parse($RightUtcIso, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal).ToUniversalTime()
        return [Math]::Abs(($left - $right).TotalSeconds) -le $ToleranceSeconds
    } catch {
        return $false
    }
}

function Get-LocalAppProcessInfo([int]$TargetProcessId) {
    try {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetProcessId" -ErrorAction Stop
        if ($null -eq $process) { return $null }
        return [pscustomobject]@{
            ProcessId = [int]$process.ProcessId
            ExecutablePath = [string]$process.ExecutablePath
            CommandLine = [string]$process.CommandLine
            CreationTimeUtc = ConvertTo-LocalAppUtcIso -Value $process.CreationDate
        }
    } catch {
        try {
            $process = Get-Process -Id $TargetProcessId -ErrorAction Stop
            return [pscustomobject]@{
                ProcessId = [int]$process.Id
                ExecutablePath = [string]$process.Path
                CommandLine = ""
                CreationTimeUtc = ConvertTo-LocalAppUtcIso -Value $process.StartTime
            }
        } catch {
            return $null
        }
    }
}

function Test-LocalAppCommandLineContains([string]$CommandLine, [string]$Needle) {
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    return $CommandLine.IndexOf($Needle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Test-LocalAppProcessIdentity {
    param(
        [Parameter(Mandatory = $true)] [object]$State,
        [Parameter(Mandatory = $true)] [string]$Root,
        [object]$ProcessInfo = $null
    )

    if ($null -eq $State) { return $false }
    foreach ($field in @("pid", "process_start_time_utc", "executable_path", "application_root", "app_module", "host", "port")) {
        if (-not (Get-Member -InputObject $State -Name $field -MemberType NoteProperty)) { return $false }
    }

    $targetProcessId = [int]$State.pid
    if ($null -eq $ProcessInfo) {
        $ProcessInfo = Get-LocalAppProcessInfo -TargetProcessId $targetProcessId
    }
    if ($null -eq $ProcessInfo) { return $false }
    if ([int]$ProcessInfo.ProcessId -ne $targetProcessId) { return $false }

    if (-not (Test-LocalAppTimeClose -LeftUtcIso ([string]$State.process_start_time_utc) -RightUtcIso ([string]$ProcessInfo.CreationTimeUtc))) {
        return $false
    }
    if (-not (Test-LocalAppPathEqual -Left ([string]$State.executable_path) -Right ([string]$ProcessInfo.ExecutablePath))) {
        return $false
    }
    if (-not (Test-LocalAppPathEqual -Left ([string]$State.application_root) -Right $Root)) {
        return $false
    }

    $commandLine = [string]$ProcessInfo.CommandLine
    if (-not (Test-LocalAppCommandLineContains -CommandLine $commandLine -Needle "-m uvicorn")) { return $false }
    if (-not (Test-LocalAppCommandLineContains -CommandLine $commandLine -Needle ([string]$State.app_module))) { return $false }
    if (-not (Test-LocalAppCommandLineContains -CommandLine $commandLine -Needle "--host $($State.host)")) { return $false }
    if (-not (Test-LocalAppCommandLineContains -CommandLine $commandLine -Needle "--port $($State.port)")) { return $false }
    if (-not (Test-LocalAppCommandLineContains -CommandLine $commandLine -Needle "--app-dir")) { return $false }
    if (-not (Test-LocalAppCommandLineContains -CommandLine $commandLine -Needle (ConvertTo-LocalAppNormalizedPath -Path ([string]$State.application_root)))) {
        return $false
    }

    return $true
}

function Read-LocalAppState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-LocalAppStateAtomically([string]$Path, [object]$Value) {
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temp = Join-Path $directory (".tmp-" + [guid]::NewGuid().ToString("N") + ".json")
    try {
        $Value | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temp -Encoding UTF8
        Move-Item -LiteralPath $temp -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
