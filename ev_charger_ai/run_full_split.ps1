# All three arms over the COMPLETE 1,909-session held-out split.
#
# A PowerShell driver rather than the bash one because this has to survive the
# Claude session that starts it: launch detached with
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#     '-File','F:\pcap_downloads\ev_charger_ai\run_full_split.ps1' -WindowStyle Hidden
#
# The earlier test_s250 results sampled 250 of 1,687 clean sessions so three arms
# would fit in an afternoon; all 222 faulty sessions were already in, so that run
# was only ever coarse on FAR. This one removes the caveat. Output goes to
# leaderboard_test.json / records_test.json and leaves the *_s250 files alone.
#
# Serialised, not parallel: a worker costs ~1.3 GB of Windows commit and little
# is free, so three concurrent benchmarks would each be capped to one worker.
param([int]$Workers = 4)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$py   = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe"
$root = "F:\pcap_downloads\ev_charger_ai"
$log  = Join-Path $root "logs\full_split.log"
Set-Location $root

function Say($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# shared by every arm: same sessions, same holdout, full split (no sampling)
$env:EV_AI_PCAPS    = "F:\pcap_downloads"
$env:EV_AI_SESSIONS = "C:\ev_iso\sessions"
$env:EV_AI_SPLIT    = "F:\pcap_downloads\ev_charger_ai\data\split.json"
Remove-Item Env:\EV_AI_CLEAN_SAMPLE -ErrorAction SilentlyContinue

$arms = @(
    @{ name = "baseline";  data = "F:\pcap_downloads\ev_charger_ai\data"; art = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline"; iso = "0"; vec = "1" },
    @{ name = "iso_rules"; data = "F:\pcap_downloads\ev_charger_ai\data"; art = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline"; iso = "1"; vec = "0" },
    @{ name = "iso";       data = "C:\ev_iso\data";                       art = "C:\ev_iso\artifacts";                                iso = "1"; vec = "1" }
)

Say "=== full held-out split, 3 arms, $Workers workers ==="
foreach ($a in $arms) {
    $res = Join-Path $root ("results\" + $a.name)
    New-Item -ItemType Directory -Force $res | Out-Null
    if (Test-Path (Join-Path $res "leaderboard_test.json")) {
        Say ("skip " + $a.name + " (leaderboard_test.json present)"); continue
    }
    $env:EV_AI_DATA      = $a.data
    $env:EV_AI_ARTIFACTS = $a.art
    $env:EV_AI_RESULTS   = $res
    $env:EV_AI_ISO       = $a.iso
    $env:EV_AI_ISO_VEC   = $a.vec
    Say ("--- arm " + $a.name + " : ISO=" + $a.iso + " VEC=" + $a.vec + " ART=" + $a.art)
    $t0 = Get-Date
    $armLog = Join-Path $root ("logs\full_" + $a.name + ".log")
    $p = Start-Process -FilePath $py -NoNewWindow -Wait -PassThru `
        -ArgumentList @("-X", "utf8", "benchmark\run_competition.py", "test", "0", "$Workers") `
        -RedirectStandardOutput $armLog -RedirectStandardError ($armLog + ".err")
    Say ("--- arm " + $a.name + " rc=" + $p.ExitCode + " in " + [math]::Round(((Get-Date)-$t0).TotalMinutes,1) + " min")
}

# analysis reads every arm's results dir, so point RESULTS back at the parent
$env:EV_AI_RESULTS = Join-Path $root "results"
Say "--- comparison ---"
& $py benchmark\compare_arms.py test 2>&1 | Tee-Object -FilePath $log -Append
Say "--- attribution ---"
& $py benchmark\attribute_alerts.py test 2>&1 | Tee-Object -FilePath $log -Append
Say "--- collected ---"
& $py benchmark\collect_report_data.py test 2>&1 | Tee-Object -FilePath $log -Append
Say "=== full split complete ==="
