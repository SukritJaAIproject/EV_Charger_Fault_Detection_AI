# Assemble the resources directory for a snapshot edition: the current dashboard
# and sidecar from a fresh `npm run desktop:prepare`, plus frozen benchmark data
# and model weights from an earlier unpacked build. Point IMPS_RESOURCES_ROOT at
# the staged directory when packaging (see desktop\README.md, "Editions").
[CmdletBinding()]
param(
    # resources directory of the frozen build (contains data\summary.json and models\)
    [Parameter(Mandatory = $true)][string]$Frozen,
    [string]$Staging = "",
    # refuse to stage anything but this model artifact
    [string]$ExpectedArtifact = ""
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "..\..")).Path
if (-not $Staging) { $Staging = Join-Path $projectRoot 'dist-desktop\snapshot-staging\resources' }
$app = Join-Path $projectRoot '.next-desktop\standalone'
$runtime = Join-Path $projectRoot '.desktop-build\runtime'
$buildManifest = Join-Path $projectRoot '.desktop-build\manifest.json'
foreach ($p in $app, $runtime, $buildManifest, (Join-Path $Frozen 'data\summary.json'), (Join-Path $Frozen 'models\manifest.json')) {
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
Mirror (Join-Path $Frozen 'models') (Join-Path $Staging 'models')
Copy-Item -LiteralPath (Join-Path $Frozen 'data\summary.json') -Destination (Join-Path $Staging 'data\summary.json') -Force

$manifest = Get-Content (Join-Path $Staging 'models\manifest.json') -Raw | ConvertFrom-Json
$summary = Get-Content (Join-Path $Staging 'data\summary.json') -Raw | ConvertFrom-Json
"staged at $Staging"
"  app files:      $((Get-ChildItem (Join-Path $Staging 'app') -Recurse -File | Measure-Object).Count)"
"  runtime files:  $((Get-ChildItem (Join-Path $Staging 'runtime') -Recurse -File | Measure-Object).Count)"
"  model artifact: $($manifest.artifactVersion)"
"  summary:        snapshotAt=$($summary.snapshotAt) faulty=$($summary.dataset.faultySessions)"
if ($ExpectedArtifact -and $manifest.artifactVersion -ne $ExpectedArtifact) {
    throw "staged model artifact $($manifest.artifactVersion) is not the expected $ExpectedArtifact"
}
$global:LASTEXITCODE = 0
exit 0
