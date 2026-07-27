[CmdletBinding()]
param(
    [string]$BaselinePython = "D:\anaconda\envs\drug-chip\python.exe",
    [string]$CandidatePython = "D:\anaconda\envs\drug-chip-portable-cpu\python.exe",
    [double]$Tolerance = 1e-6,
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function RepoRoot { return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
function Info([string]$Message) { Write-Host "[info] $Message" }

function Run-Predictions([string]$Python, [string]$Helper, [string]$Root, [string]$Output) {
    $env:FORWARD_MODEL_DEVICE = "cpu"
    $oldModelDevice = [Environment]::GetEnvironmentVariable("MODEL_DEVICE", "Process")
    $oldModelSourceRoot = [Environment]::GetEnvironmentVariable("MODEL_SOURCE_ROOT", "Process")
    [Environment]::SetEnvironmentVariable("MODEL_DEVICE", $null, "Process")
    [Environment]::SetEnvironmentVariable("MODEL_SOURCE_ROOT", $null, "Process")
    try {
        & $Python $Helper --root $Root --output $Output
        if ($LASTEXITCODE -ne 0) { throw "Prediction helper failed for $Python" }
    } finally {
        [Environment]::SetEnvironmentVariable("MODEL_DEVICE", $oldModelDevice, "Process")
        [Environment]::SetEnvironmentVariable("MODEL_SOURCE_ROOT", $oldModelSourceRoot, "Process")
        Remove-Item Env:FORWARD_MODEL_DEVICE -ErrorAction SilentlyContinue
    }
}

$root = RepoRoot
if (-not (Test-Path -LiteralPath $BaselinePython)) { throw "Baseline Python not found: $BaselinePython" }
if (-not (Test-Path -LiteralPath $CandidatePython)) { throw "Candidate Python not found: $CandidatePython" }

$reportDir = Join-Path $root ".build\reports\prediction-parity"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$helper = Join-Path $reportDir "predict_forward_payloads.py"
$baselineOut = Join-Path $reportDir "baseline.json"
$candidateOut = Join-Path $reportDir "candidate.json"
$summaryPath = if ($OutputPath.Trim()) { $OutputPath } else { Join-Path $reportDir "summary.json" }

@'
import argparse
import json
import os
import sys
from pathlib import Path

PAYLOADS = [
    {
        "sample_name": "frontend-example",
        "inlet1": 1.0,
        "inlet2": 0.0,
        "chips": [
            {"position": 1, "chip_type": "5to4", "left_width_mm": 1.1, "right_width_mm": 1.2, "left_bend_straight_distance_mm": 11.0, "right_bend_straight_distance_mm": 21.0},
            {"position": 2, "chip_type": "4to2", "left_width_mm": 2.1, "right_width_mm": 2.2, "left_bend_straight_distance_mm": 12.0, "right_bend_straight_distance_mm": 22.0},
            {"position": 3, "chip_type": "1to6", "left_width_mm": 3.1, "right_width_mm": 3.2, "left_bend_straight_distance_mm": 13.0, "right_bend_straight_distance_mm": 23.0},
            {"position": 4, "chip_type": "2to4", "left_width_mm": 4.1, "right_width_mm": 4.2, "left_bend_straight_distance_mm": 14.0, "right_bend_straight_distance_mm": 24.0},
            {"position": 5, "chip_type": "6to3", "left_width_mm": 5.1, "right_width_mm": 5.2, "left_bend_straight_distance_mm": 15.0, "right_bend_straight_distance_mm": 25.0},
            {"position": 6, "chip_type": "3to1", "left_width_mm": 6.1, "right_width_mm": 6.2, "left_bend_straight_distance_mm": 16.0, "right_bend_straight_distance_mm": 26.0},
        ],
    },
    {
        "sample_name": "alternate-widths",
        "inlet1": 0.65,
        "inlet2": 0.35,
        "chips": [
            {"position": 1, "chip_type": "1to6", "left_width_mm": 1.8, "right_width_mm": 1.4, "left_bend_straight_distance_mm": 9.0, "right_bend_straight_distance_mm": 18.0},
            {"position": 2, "chip_type": "2to4", "left_width_mm": 2.6, "right_width_mm": 2.0, "left_bend_straight_distance_mm": 10.0, "right_bend_straight_distance_mm": 19.0},
            {"position": 3, "chip_type": "3to1", "left_width_mm": 3.4, "right_width_mm": 2.7, "left_bend_straight_distance_mm": 11.0, "right_bend_straight_distance_mm": 20.0},
            {"position": 4, "chip_type": "4to2", "left_width_mm": 4.2, "right_width_mm": 3.3, "left_bend_straight_distance_mm": 12.0, "right_bend_straight_distance_mm": 21.0},
            {"position": 5, "chip_type": "5to4", "left_width_mm": 5.0, "right_width_mm": 4.1, "left_bend_straight_distance_mm": 13.0, "right_bend_straight_distance_mm": 22.0},
            {"position": 6, "chip_type": "6to3", "left_width_mm": 5.8, "right_width_mm": 4.9, "left_bend_straight_distance_mm": 14.0, "right_bend_straight_distance_mm": 23.0},
        ],
    },
    {
        "sample_name": "structure-coverage",
        "inlet1": 0.25,
        "inlet2": 0.75,
        "chips": [
            {"position": 1, "chip_type": "6to3", "left_width_mm": 1.3, "right_width_mm": 1.7, "left_bend_straight_distance_mm": 7.5, "right_bend_straight_distance_mm": 17.5},
            {"position": 2, "chip_type": "5to4", "left_width_mm": 2.3, "right_width_mm": 2.8, "left_bend_straight_distance_mm": 8.5, "right_bend_straight_distance_mm": 18.5},
            {"position": 3, "chip_type": "4to2", "left_width_mm": 3.3, "right_width_mm": 3.9, "left_bend_straight_distance_mm": 9.5, "right_bend_straight_distance_mm": 19.5},
            {"position": 4, "chip_type": "3to1", "left_width_mm": 4.3, "right_width_mm": 5.0, "left_bend_straight_distance_mm": 10.5, "right_bend_straight_distance_mm": 20.5},
            {"position": 5, "chip_type": "2to4", "left_width_mm": 5.3, "right_width_mm": 6.1, "left_bend_straight_distance_mm": 11.5, "right_bend_straight_distance_mm": 21.5},
            {"position": 6, "chip_type": "1to6", "left_width_mm": 6.3, "right_width_mm": 7.2, "left_bend_straight_distance_mm": 12.5, "right_bend_straight_distance_mm": 22.5},
        ],
    },
]

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root / "backend"))
    os.chdir(root)
    os.environ["FORWARD_MODEL_DEVICE"] = "cpu"
    os.environ.pop("MODEL_DEVICE", None)
    os.environ.pop("MODEL_SOURCE_ROOT", None)

    from app.core.config import ForwardModelSettings
    from app.model_runtime.forward_adapter import ForwardModelAdapter
    from app.schemas.forward import ForwardPredictionRequest

    adapter = ForwardModelAdapter(ForwardModelSettings.from_env())
    responses = []
    for payload in PAYLOADS:
        request = ForwardPredictionRequest(**payload)
        response = adapter.predict(request)
        responses.append(response.model_dump())
    Path(args.output).write_text(json.dumps(responses, indent=2, sort_keys=True), encoding="utf-8")

if __name__ == "__main__":
    main()
'@ | Set-Content -LiteralPath $helper -Encoding UTF8

Info "Running baseline predictions with $BaselinePython"
Run-Predictions -Python $BaselinePython -Helper $helper -Root $root -Output $baselineOut
Info "Running candidate predictions with $CandidatePython"
Run-Predictions -Python $CandidatePython -Helper $helper -Root $root -Output $candidateOut

$baseline = Get-Content -LiteralPath $baselineOut -Raw | ConvertFrom-Json
$candidate = Get-Content -LiteralPath $candidateOut -Raw | ConvertFrom-Json
if ($baseline.Count -ne $candidate.Count) { throw "Payload count differs." }

$maxAbs = 0.0
$maxRel = 0.0
$comparisons = 0
for ($payloadIndex = 0; $payloadIndex -lt $baseline.Count; $payloadIndex++) {
    $left = $baseline[$payloadIndex]
    $right = $candidate[$payloadIndex]
    if ($left.predictions.Count -ne $right.predictions.Count) { throw "Prediction count differs for payload $payloadIndex." }
    for ($i = 0; $i -lt $left.predictions.Count; $i++) {
        $a = $left.predictions[$i]
        $b = $right.predictions[$i]
        if ($a.position -ne $b.position -or $a.point -ne $b.point -or $a.chip_type -ne $b.chip_type) {
            throw "Prediction order or labels differ for payload $payloadIndex position $($i + 1)."
        }
        $av = [double]$a.concentration
        $bv = [double]$b.concentration
        $abs = [math]::Abs($av - $bv)
        $rel = if ([math]::Abs($av) -gt 0) { $abs / [math]::Abs($av) } else { $abs }
        $maxAbs = [math]::Max($maxAbs, $abs)
        $maxRel = [math]::Max($maxRel, $rel)
        $comparisons += 1
    }
}

$passed = ($maxAbs -le $Tolerance)
$summary = [ordered]@{
    payload_count = $baseline.Count
    comparisons = $comparisons
    tolerance = $Tolerance
    max_absolute_difference = $maxAbs
    max_relative_difference = $maxRel
    passed = $passed
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Info "Prediction parity summary: $($summary | ConvertTo-Json -Compress)"
if (-not $passed) { throw "Prediction parity failed: max absolute difference $maxAbs exceeds tolerance $Tolerance." }
