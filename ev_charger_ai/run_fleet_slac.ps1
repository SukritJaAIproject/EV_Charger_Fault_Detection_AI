# Replay the SLAC arm over the full-fleet held-out split.
#
# SLAC_FAILURE is 224 of 957 held-out faults (23%) and the family ISO 15118-2
# cannot describe -- PLC matching is part 3. Four of five detectors score 0-21%
# on it because nothing in the 33-feature vector tracks the matching sequence.
# core/slac_features.py adds that view as fs.slac and adds NO vector columns,
# so the fleet's own weights load unchanged and this is a single replay:
# exactly the same models, sessions and labels as the fleet baseline, with one
# rule layer switched on.
#
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#     '-File','F:\pcap_downloads\ev_charger_ai\run_fleet_slac.ps1' -WindowStyle Hidden
#
# The replay is checkpointed per connector (EV_AI_CKPT below), so a crash costs
# one connector instead of the whole run and the retry loop simply picks up
# where the pool died. That is not hypothetical: on 2026-09-16 a worker was
# killed 18 minutes in, cf.ProcessPoolExecutor raised BrokenProcessPool, and
# 8,820 sessions of work went with it because records were only written at the
# end.
param(
    [string]$Sessions = "C:\ev_fleet\sessions",
    [int]$Workers = 11,
    [string]$Wait = "10",
    [ValidateSet("empirical", "normative", "both")]
    [string]$RuleMode = "empirical",
    [int]$Attempts = 4
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py   = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe"
$root = "F:\pcap_downloads\ev_charger_ai"
$tag  = if ($RuleMode -eq "empirical") { "fleet_slac" } else { "fleet_slac_$RuleMode" }
$log  = Join-Path $root "logs\$tag.log"
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
$env:EV_AI_ARTIFACTS  = "E:\ev_charger_ai_data\artifacts"
$env:EV_AI_RESULTS    = Join-Path $root "results\$tag"
$env:EV_AI_SLAC       = "1"
$env:EV_AI_SLAC_WAIT  = $Wait
$env:EV_AI_SLAC_RULE_MODE = $RuleMode
$env:EV_AI_ISO        = "0"          # SLAC alone, so its effect is separable
$env:EV_AI_CKPT       = "C:\ev_fleet\ckpt"   # NVMe: shards are written hot
Remove-Item Env:\EV_AI_CLEAN_SAMPLE -ErrorAction SilentlyContinue
Remove-Item Env:\EV_AI_INDEX -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $env:EV_AI_RESULTS | Out-Null

Say "=== fleet SLAC replay: mode=$RuleMode fleet_wait=${Wait}s workers=$Workers sessions=$Sessions ==="
$t0 = Get-Date
$out = Join-Path $root "logs\${tag}_bench.log"
$rc = 1
# clear previous attempts first: the concatenation below must not fold in a
# stale traceback from an earlier invocation and present it as this run's tail
Get-ChildItem "$out.*" -ErrorAction SilentlyContinue | Remove-Item -Force
$last = 0
for ($i = 1; $i -le $Attempts -and $rc -ne 0; $i++) {
    $last = $i
    if ($i -gt 1) { Say "attempt $i/$Attempts (resuming from checkpoint)" }
    $p = Start-Process -FilePath $py -NoNewWindow -Wait -PassThru `
        -ArgumentList @("-X", "utf8", "benchmark\run_competition.py", "test", "0", "$Workers") `
        -RedirectStandardOutput "$out.$i" -RedirectStandardError "$out.$i.err"
    $rc = $p.ExitCode
    Say ("attempt $i rc=$rc after " + [math]::Round(((Get-Date) - $t0).TotalMinutes, 1) + " min")
}
$merged = foreach ($n in 1..$last) {
    foreach ($f in @("$out.$n", "$out.$n.err")) {
        if (Test-Path $f) { "--- attempt $n : $(Split-Path $f -Leaf) ---"; Get-Content $f }
    }
}
$merged | Set-Content $out -Encoding UTF8
if ($rc -ne 0) {
    Say "replay never completed (rc=$rc after $Attempts attempts) -- NOT comparing arms"
    exit 1
}

$env:EV_AI_RESULTS = Join-Path $root "results"
Say "--- fleet: baseline vs $tag vs ISO rules ---"
& $py benchmark\compare_arms.py test "fleet_baseline,$tag,fleet_iso_rules" 2>&1 |
    Tee-Object -FilePath $log -Append
Say "--- fleet SLAC attribution ($RuleMode) ---"
& $py benchmark\attribute_alerts.py test $tag 2>&1 | Tee-Object -FilePath $log -Append
Say "=== fleet SLAC complete: $tag ==="
