# Assemble the resources directory for one desktop edition: the current dashboard
# and sidecar from a fresh `npm run desktop:prepare`, plus that edition's benchmark
# summary, model weights, favicon and optional extra data files. Point
# IMPS_RESOURCES_ROOT at the staged directory when packaging (see desktop\README.md,
# "Editions"). Every edition is staged, because the browser-tab favicon lives inside
# the shared Next app and electron-builder copies extraResources concurrently, so it
# cannot be overridden by a second resource entry.
[CmdletBinding()]
param(
    # edition key; the staging folder is dist-desktop\staging\<Name>\resources
    [Parameter(Mandatory = $true)][string]$Name,
    # benchmark summary to bundle as data\summary.json
    [Parameter(Mandatory = $true)][string]$Summary,
    # directory with lstm_ae.npz, gru_fore.npz and manifest.json
    [Parameter(Mandatory = $true)][string]$Models,
    # directory with favicon.png (desktop\icons\<edition>); omit to keep the app's own
    [string]$IconDir = "",
    # directory whose files are copied into data\ next to summary.json (e.g. detection-policy.json)
    [string]$ExtraData = "",
    # refuse to stage anything but this model artifact
    [string]$ExpectedArtifact = "",
    [string]$Staging = ""
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\..")).Path
if (-not $Staging) { $Staging = Join-Path $projectRoot "dist-desktop\staging\$Name\resources" }
$app = Join-Path $projectRoot '.next-desktop\standalone'
$runtime = Join-Path $projectRoot '.desktop-build\runtime'
$buildManifest = Join-Path $projectRoot '.desktop-build\manifest.json'
$required = @($app, $runtime, $buildManifest, $Summary, (Join-Path $Models 'manifest.json'))
if ($IconDir) { $required += (Join-Path $IconDir 'favicon.png') }
if ($ExtraData) { $required += $ExtraData }
foreach ($p in $required) {
    if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" }
}
$serverEntry = (Get-Content $buildManifest -Raw | ConvertFrom-Json).nextServerRelativePath
if ($serverEntry -ne 'server.js') { throw "unexpected standalone layout: server entry is $serverEntry" }

if (Test-Path -LiteralPath $Staging) { [IO.Directory]::Delete($Staging, $true) }
New-Item -ItemType Directory -Force (Join-Path $Staging 'data') | Out-Null
function Mirror($from, $to) {
    # robocopy exit codes below 8 mean success (1 = files copied)
    & robocopy $from $to /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:2 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE): $from -> $to" }
}
Mirror $app (Join-Path $Staging 'app')
Mirror $runtime (Join-Path $Staging 'runtime')
Mirror $Models (Join-Path $Staging 'models')
Copy-Item -LiteralPath $Summary -Destination (Join-Path $Staging 'data\summary.json') -Force
if ($ExtraData) {
    Get-ChildItem -LiteralPath $ExtraData -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Staging "data\$($_.Name)") -Force
    }
}
if ($IconDir) {
    Copy-Item -LiteralPath (Join-Path $IconDir 'favicon.png') -Destination (Join-Path $Staging 'app\public\img\favicon.png') -Force
}

$manifest = Get-Content (Join-Path $Staging 'models\manifest.json') -Raw | ConvertFrom-Json
$summaryJson = Get-Content (Join-Path $Staging 'data\summary.json') -Raw | ConvertFrom-Json
"staged $Name at $Staging"
"  app files:      $((Get-ChildItem (Join-Path $Staging 'app') -Recurse -File | Measure-Object).Count)"
"  runtime files:  $((Get-ChildItem (Join-Path $Staging 'runtime') -Recurse -File | Measure-Object).Count)"
"  model artifact: $($manifest.artifactVersion)"
"  summary:        snapshotAt=$($summaryJson.snapshotAt) faulty=$($summaryJson.dataset.faultySessions) stations=$(@($summaryJson.analysis.byStation).Count)"
"  data files:     $((Get-ChildItem (Join-Path $Staging 'data') -File | ForEach-Object { $_.Name }) -join ', ')"
"  favicon:        $(if ($IconDir) { 'from ' + $IconDir } else { 'app default' })"
if ($ExpectedArtifact -and $manifest.artifactVersion -ne $ExpectedArtifact) {
    throw "staged model artifact $($manifest.artifactVersion) is not the expected $ExpectedArtifact"
}
$global:LASTEXITCODE = 0
exit 0
