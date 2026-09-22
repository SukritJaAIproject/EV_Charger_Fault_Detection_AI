# Replay the iso_rules arm over the FULL-FLEET held-out split.
#
# The fleet pipeline (run_full_fleet.ps1, complete 2026-09-12) trained and
# benchmarked the baseline arm only: 212 stations, 40,542 sessions, held-out
# 957 faulty / 7,863 clean across 45 never-seen stations, strict labels. That
# is a 5x larger and far more diverse test bed than the 37-station experiment
# the ISO findings rest on. iso_rules needs nothing new — the fleet's own
# 33-feature weights plus the ISO rule layer (EV_AI_ISO=1, EV_AI_ISO_VEC=0) —
# so it is one replay, and the comparison against the fleet's existing
# leaderboard_test.json is exact: same weights, same sessions, same labels.
#
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#     '-File','F:\pcap_downloads\ev_charger_ai\run_fleet_iso_rules.ps1',
#     '-Sessions','C:\ev_fleet\sessions','-Workers','16' -WindowStyle Hidden
param(
    [string]$Sessions = "E:\ev_charger_ai_data\sessions",
    [int]$Workers = 16
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py   = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe"
$root = "F:\pcap_downloads\ev_charger_ai"
$log  = Join-Path $root "logs\fleet_iso_rules.log"
Set-Location $root

function Say($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:EV_AI_PCAPS      = "E:\pcap_downloads"
$env:EV_AI_DATA       = "E:\ev_charger_ai_data"
$env:EV_AI_SESSIONS   = $Sessions
$env:EV_AI_SPLIT      = "E:\ev_charger_ai_data\split.json"
$env:EV_AI_ARTIFACTS  = "E:\ev_charger_ai_data\artifacts"      # the fleet's own weights
$env:EV_AI_RESULTS    = Join-Path $root "results\fleet_iso_rules"
$env:EV_AI_ISO        = "1"
$env:EV_AI_ISO_VEC    = "0"                                     # 33 wide: fleet weights load unchanged
Remove-Item Env:\EV_AI_CLEAN_SAMPLE -ErrorAction SilentlyContinue   # full split, no sampling
Remove-Item Env:\EV_AI_INDEX -ErrorAction SilentlyContinue          # fleet index.json is already strict
New-Item -ItemType Directory -Force $env:EV_AI_RESULTS | Out-Null

Say "=== fleet iso_rules replay: sessions=$Sessions workers=$Workers ==="
$t0 = Get-Date
$out = Join-Path $root "logs\fleet_iso_rules_bench.log"
$p = Start-Process -FilePath $py -NoNewWindow -Wait -PassThru `
    -ArgumentList @("-X", "utf8", "benchmark\run_competition.py", "test", "0", "$Workers") `
    -RedirectStandardOutput $out -RedirectStandardError ($out + ".err")
Say ("replay rc=" + $p.ExitCode + " in " + [math]::Round(((Get-Date) - $t0).TotalMinutes, 1) + " min")

# put the fleet's baseline leaderboard beside it so compare_arms can read both
$fb = Join-Path $root "results\fleet_baseline"
New-Item -ItemType Directory -Force $fb | Out-Null
Copy-Item "E:\ev_charger_ai_data\results\leaderboard_test.json" (Join-Path $fb "leaderboard_test.json") -Force
Copy-Item "E:\ev_charger_ai_data\results\records_test.json"     (Join-Path $fb "records_test.json") -Force

$env:EV_AI_RESULTS = Join-Path $root "results"
Say "--- fleet: baseline vs iso_rules ---"
& $py benchmark\compare_arms.py test fleet_baseline,fleet_iso_rules 2>&1 | Tee-Object -FilePath $log -Append
Say "--- fleet attribution ---"
& $py benchmark\attribute_alerts.py test fleet_baseline,fleet_iso_rules 2>&1 | Tee-Object -FilePath $log -Append
Say "=== fleet iso_rules complete ==="
