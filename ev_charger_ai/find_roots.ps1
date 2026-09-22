# Print one resolved path, so a .cmd wrapper can set env vars without baking in
# a drive letter. The data volume is USB and its letter has already moved
# between E:, F: and G:.
#
#   find_roots.ps1 data v4     -> <drive>\ev_charger_ai_data_v4   (created if absent)
#   find_roots.ps1 telemetry   -> the shared telemetry tree
#   find_roots.ps1 pcaps       -> the pcap root with the most stations
#   find_roots.ps1 prevsplit   -> split.json of the newest finished run
param(
    [Parameter(Mandatory = $true)][string]$What,
    [string]$Suffix = ""
)

$ErrorActionPreference = "Stop"

function Drives {
    Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[D-Z]:' } |
        ForEach-Object { $_.Root }
}

function Find-Named([string]$name, [string]$marker) {
    foreach ($d in Drives) {
        $p = Join-Path $d $name
        if (Test-Path $p) {
            if (-not $marker -or (Test-Path (Join-Path $p $marker))) { return $p }
        }
    }
    return $null
}

switch ($What) {
    "pcaps" {
        # several drives carry a folder of this name (an empty one left on the
        # volume that took the old letter, an older copy beside the checkout);
        # the real fleet is the one with the most station\connector folders
        $best = $null; $bestN = 0
        foreach ($d in Drives) {
            $p = Join-Path $d "pcap_downloads"
            if (-not (Test-Path $p)) { continue }
            $n = (Get-ChildItem $p -Directory -ErrorAction SilentlyContinue |
                  Where-Object { Test-Path (Join-Path $_.FullName "connector1") } |
                  Measure-Object).Count
            if ($n -gt $bestN) { $best = $p; $bestN = $n }
        }
        if ($best) { $best }
    }
    "telemetry" {
        $r = Find-Named "ev_charger_ai_data" "telemetry\manifest.json"
        if ($r) { Join-Path $r "telemetry" }
    }
    "prevsplit" {
        foreach ($n in @("ev_charger_ai_data_v3", "ev_charger_ai_data")) {
            $r = Find-Named $n "split.json"
            if ($r) { Join-Path $r "split.json"; break }
        }
    }
    "data" {
        $name = if ($Suffix) { "ev_charger_ai_data_$Suffix" } else { "ev_charger_ai_data" }
        $existing = Find-Named $name
        if ($existing) { $existing }
        else {
            # put a new run beside the previous one, on the volume that has the data
            $anchor = Find-Named "ev_charger_ai_data" "sessions\index.json"
            if (-not $anchor) { exit 1 }
            $p = Join-Path (Split-Path $anchor -Qualifier) "\$name"
            New-Item -ItemType Directory -Force $p | Out-Null
            $p
        }
    }
    default { exit 1 }
}
