# Retrain and re-benchmark all three arms on the CORRECTED ground truth.
#
# pipeline/relabel.py found that 141 of 264 SESSION_ABORTs (a fifth of every
# fault in the dataset) were captures that ended rather than dialogs that broke.
# benchmark/rescore_labels.py already re-scored the existing alert records
# against the fix — but the learned layers (XGBoost horizon targets, the DQN's
# rewards, the autoencoder's clean-session pool) were still fitted against the
# old truth. This retrains them and replays.
#
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#     '-File','F:\pcap_downloads\ev_charger_ai\run_relabeled.ps1' -WindowStyle Hidden
#
# Results land under results/<arm>_v2/ and the v1 weights and leaderboards are
# left untouched, so the published numbers stay reproducible side by side.
param([int]$Workers = 4)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$py   = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe"
$root = "F:\pcap_downloads\ev_charger_ai"
$log  = Join-Path $root "logs\relabeled.log"
Set-Location $root

function Say($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    # Write-Host, NOT Write-Output: a PowerShell function returns everything
    # written to the output stream, so a Say() inside Run() would be prepended
    # to the exit code and "(Run ...) -ne 0" would compare an ARRAY - always
    # true, aborting after a stage that in fact succeeded.
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# NB: not $args — that is a PowerShell automatic variable and a
# parameter of that name is silently shadowed, launching python
# with no script at all (it drops into an interactive REPL).
function Run($name, $argv, $envs) {
    foreach ($k in $envs.Keys) { Set-Item -Path ("Env:\" + $k) -Value $envs[$k] }
    Say "--- START $name"
    $t0 = Get-Date
    $out = Join-Path $root ("logs\relabeled_" + $name + ".log")
    $p = Start-Process -FilePath $py -NoNewWindow -Wait -PassThru `
        -ArgumentList (@("-X", "utf8") + $argv) `
        -RedirectStandardOutput $out -RedirectStandardError ($out + ".err")
    Say ("--- END   $name rc=" + $p.ExitCode + " in " +
         [math]::Round(((Get-Date) - $t0).TotalMinutes, 1) + " min")
    return $p.ExitCode
}

# shared across everything: same sessions, same holdout, same 472-session sample
# as the v1 leaderboards so the two are directly comparable
$common = @{
    EV_AI_PCAPS        = "F:\pcap_downloads"
    EV_AI_SESSIONS     = "C:\ev_iso\sessions"
    EV_AI_SPLIT        = "F:\pcap_downloads\ev_charger_ai\data\split.json"
    EV_AI_CLEAN_SAMPLE = "250"
}

Say "=== retrain + replay on corrected labels ==="

# ---- 1. baseline weights: 33 features, matrices sliced onto the NVMe --------
$e = $common.Clone()
$e.EV_AI_DATA = "C:\ev_iso\data33"; $e.EV_AI_ARTIFACTS = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline_v2"
$e.EV_AI_ISO = "0"; $e.EV_AI_ISO_VEC = "1"
New-Item -ItemType Directory -Force $e.EV_AI_ARTIFACTS | Out-Null
# each stage writes one artifact last; if it is already there the stage is done
$marks = @{ "train\train_traditional.py" = "traditional.joblib"
            "train\train_nn_tools.py"    = "gru_fore.pt"
            "train\train_rl.py"          = "dqn.pt" }
foreach ($s in @("train\train_traditional.py", "train\train_nn_tools.py", "train\train_rl.py")) {
    $tag = "base_" + [IO.Path]::GetFileNameWithoutExtension($s)
    if (Test-Path (Join-Path $e.EV_AI_ARTIFACTS $marks[$s])) { Say "skip $tag (already built)"; continue }
    $rc = Run $tag @($s) $e
    if ($rc -ne 0) { Say "!! baseline training failed rc=$rc, aborting"; exit 1 }
}

# ---- 2. iso weights: 60 features -------------------------------------------
$e = $common.Clone()
$e.EV_AI_DATA = "C:\ev_iso\data"; $e.EV_AI_ARTIFACTS = "C:\ev_iso\artifacts_v2"
$e.EV_AI_ISO = "1"; $e.EV_AI_ISO_VEC = "1"
New-Item -ItemType Directory -Force $e.EV_AI_ARTIFACTS | Out-Null
foreach ($s in @("train\train_traditional.py", "train\train_nn_tools.py", "train\train_rl.py")) {
    $tag = "iso_" + [IO.Path]::GetFileNameWithoutExtension($s)
    if (Test-Path (Join-Path $e.EV_AI_ARTIFACTS $marks[$s])) { Say "skip $tag (already built)"; continue }
    $rc = Run $tag @($s) $e
    if ($rc -ne 0) { Say "!! iso training failed rc=$rc, aborting"; exit 1 }
}

# ---- 3. replay all three arms ----------------------------------------------
$arms = @(
    @{ n = "baseline_v2";  data = "C:\ev_iso\data33"; art = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline_v2"; iso = "0"; vec = "1" },
    @{ n = "iso_rules_v2"; data = "C:\ev_iso\data33"; art = "F:\pcap_downloads\ev_charger_ai\artifacts_baseline_v2"; iso = "1"; vec = "0" },
    @{ n = "iso_v2";       data = "C:\ev_iso\data";   art = "C:\ev_iso\artifacts_v2";                                 iso = "1"; vec = "1" }
)
foreach ($a in $arms) {
    $res = Join-Path $root ("results\" + $a.n)
    New-Item -ItemType Directory -Force $res | Out-Null
    $e = $common.Clone()
    $e.EV_AI_DATA = $a.data; $e.EV_AI_ARTIFACTS = $a.art; $e.EV_AI_RESULTS = $res
    $e.EV_AI_ISO = $a.iso; $e.EV_AI_ISO_VEC = $a.vec
    Run ("bench_" + $a.n) @("benchmark\run_competition.py", "test", "0", "$Workers") $e | Out-Null
}

# ---- 4. compare -------------------------------------------------------------
$env:EV_AI_RESULTS = Join-Path $root "results"
Say "--- v2 comparison (retrained on corrected labels) ---"
& $py benchmark\compare_arms.py test_s250 baseline_v2,iso_rules_v2,iso_v2 2>&1 |
    Tee-Object -FilePath $log -Append
Say "--- v2 attribution ---"
& $py benchmark\attribute_alerts.py test_s250 baseline_v2,iso_rules_v2,iso_v2 2>&1 |
    Tee-Object -FilePath $log -Append
Say "=== relabelled run complete ==="
