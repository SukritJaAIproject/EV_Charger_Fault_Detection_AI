[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$ModelPython = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe",
    [string]$ModelSource = "G:\ev_charger_ai_data_v4\artifacts",
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
$runtimeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $runtimeRoot "..\..")).Path
$buildRoot = Join-Path $projectRoot ".desktop-build"
$outputRoot = Join-Path $buildRoot "runtime"
$modelsRoot = Join-Path $buildRoot "models"
$distRoot = Join-Path $buildRoot "pyinstaller-dist"
$workRoot = Join-Path $buildRoot "pyinstaller-work"
$spec = Join-Path $runtimeRoot "imps_fault_runtime.spec"

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
if (-not $SkipModels) {
    if (-not (Test-Path -LiteralPath $ModelPython -PathType Leaf)) {
        throw "Model conversion Python does not exist: $ModelPython"
    }
    & $ModelPython (Join-Path $runtimeRoot "build_models.py") `
        --source $ModelSource --output $modelsRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Model conversion failed with exit code $LASTEXITCODE"
    }
}

& $Python -m PyInstaller --noconfirm --clean `
    --distpath $distRoot --workpath $workRoot $spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$builtRoot = Join-Path $distRoot "imps-fault-runtime"
$builtExe = Join-Path $builtRoot "imps-fault-runtime.exe"
if (-not (Test-Path -LiteralPath $builtExe -PathType Leaf)) {
    throw "PyInstaller output is missing: $builtExe"
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

# Replace only this sidecar's outputs.  A separately prepared portable
# Wireshark bundle at runtime\wireshark is deliberately preserved.
$outputExe = Join-Path $outputRoot "imps-fault-runtime.exe"
$outputInternal = Join-Path $outputRoot "_internal"
if (Test-Path -LiteralPath $outputExe) {
    Remove-Item -LiteralPath $outputExe -Force
}
if (Test-Path -LiteralPath $outputInternal) {
    $resolvedInternal = (Resolve-Path -LiteralPath $outputInternal).Path
    if (-not $resolvedInternal.StartsWith($outputRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace an unexpected PyInstaller support path"
    }
    Remove-Item -LiteralPath $resolvedInternal -Recurse -Force
}
Get-ChildItem -LiteralPath $builtRoot -Force | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $outputRoot -Recurse -Force
}

if (-not (Test-Path -LiteralPath $outputExe -PathType Leaf)) {
    throw "Runtime executable was not copied to its packaging location"
}
& $outputExe serve --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Runtime executable self-check failed with exit code $LASTEXITCODE"
}

$modelManifest = Get-Content -LiteralPath (Join-Path $modelsRoot "manifest.json") -Raw |
    ConvertFrom-Json

[pscustomobject]@{
    Runtime = $outputExe
    Models = $modelsRoot
    ArtifactVersion = $modelManifest.artifactVersion
} | ConvertTo-Json -Compress
