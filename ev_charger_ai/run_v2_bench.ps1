# Replay the three arms with the weights retrained on the corrected labels.
#
# The retrain half of run_relabeled.ps1 finished on 2026-09-10; the replay half
# died with a reboot. Rather than resume that serialised chain, this runs the
# three replays CONCURRENTLY — on a freshly booted machine the commit ceiling
# that forced serialisation before is not binding (each worker is ~1.3 GB, and
# 3 arms x 6 workers fits with room to spare).
#
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#     '-File','F:\pcap_downloads\ev_charger_ai\run_v2_bench.ps1' -WindowStyle Hidden
param([int]$Workers = 6)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py   = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe"
$root = "F:\pcap_downloads\ev_charger_ai"
$log  = Join-Path $root "logs\v2_bench.log"
Set-Location $root

function Say($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

$env:PYTHONIOENCODING   = "utf-8"
$env:PYTHONUNBUFFERED   = "1"
$env:EV_AI_PCAPS        = "F:\pcap_downloads"
$env:EV_AI_SESSIONS     = "C:\ev_iso\sessions"
$env:EV_AI_SPLIT        = "F:\pcap_downloads\ev_charger_ai\data\split.json"
$env:EV_AI_CLEAN_SAMPLE = "250"        # the same 472-session sample as v1

$arms = @(
    @{ n = "baseline_v2";  data = "C:\ev_iso\data33"; art = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline_v2"; iso = "0"; vec = "1" },
    @{ n = "iso_rules_v2"; data = "C:\ev_iso\data33"; art = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline_v2"; iso = "1"; vec = "0" },
    @{ n = "iso_v2";       data = "C:\ev_iso\data";   art = "C:\ev_iso\artifacts_v2";                                 iso = "1"; vec = "1" }
)

Say "=== v2 replay: 3 arms concurrently, $Workers workers each ==="
$procs = @()
foreach ($a in $arms) {
    $res = Join-Path $root ("results\" + $a.n)
    New-Item -ItemType Directory -Force $res | Out-Null
    if (Test-Path (Join-Path $res "leaderboard_test_s250.json")) { Say ("skip " + $a.n); continue }
    # children inherit the environment as it stands at launch
    $env:EV_AI_DATA = $a.data; $env:EV_AI_ARTIFACTS = $a.art; $env:EV_AI_RESULTS = $res
    $env:EV_AI_ISO = $a.iso;   $env:EV_AI_ISO_VEC = $a.vec
    $out = Join-Path $root ("logs\v2_bench_" + $a.n + ".log")
    $p = Start-Process -FilePath $py -NoNewWindow -PassThru `
        -ArgumentList @("-X", "utf8", "benchmark\run_competition.py", "test", "0", "$Workers") `
        -RedirectStandardOutput $out -RedirectStandardError ($out + ".err")
    Say ("launched " + $a.n + " pid " + $p.Id)
    $procs += @{ n = $a.n; p = $p; t0 = Get-Date }
}
foreach ($x in $procs) {
    $x.p.WaitForExit()
    Say ($x.n + " rc=" + $x.p.ExitCode + " in " + [math]::Round(((Get-Date) - $x.t0).TotalMinutes, 1) + " min")
}

$env:EV_AI_RESULTS = Join-Path $root "results"
Say "--- v2 comparison (retrained on corrected labels) ---"
& $py benchmark\compare_arms.py test_s250 baseline_v2,iso_rules_v2,iso_v2 2>&1 | Tee-Object -FilePath $log -Append
Say "--- v2 attribution ---"
& $py benchmark\attribute_alerts.py test_s250 baseline_v2,iso_rules_v2,iso_v2 2>&1 | Tee-Object -FilePath $log -Append
Say "=== v2 replay complete ==="
