# Full-fleet pipeline driver: pcaps on E: -> telemetry -> sessions -> split ->
# dataset -> 5 trained models -> competition -> analysis.
#
# Designed for a ~20-hour run on a shared machine:
#   * every stage writes logs/<stage>.log and a logs/<stage>.done marker
#   * re-running skips stages whose marker exists (resume after a crash or a
#     session restart); -From <stage> or -Force to redo
#   * extraction runs twice: the second pass picks up pcaps the downloader
#     finished while the first pass was busy (resumable, cheap) and rebuilds
#     the manifest
#   * launch DETACHED so it does not die with the shell that started it:
#       Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
#         '-File','F:\pcap_downloads\ev_charger_ai\run_full_fleet.ps1' -WindowStyle Hidden
#
# Progress: Get-Content E:\ev_charger_ai_data\logs\driver.log -Tail 20
#   (poll with Get-Content; do NOT hold the file open with `tail -F` - see Log)
param(
    [string]$From = "",
    [switch]$Force,
    [int]$ExtractWorkers = 12,
    [int]$SessionizeWorkers = 4,
    [int]$DatasetWorkers = 12,
    [int]$BenchWorkers = 18
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$py   = "C:\Users\user1\anaconda3\envs\ev_ai\python.exe"
$root = "F:\pcap_downloads\ev_charger_ai"
# No hardcoded drive letter: USB volumes re-enumerate and this tree has
# already moved between E:, F: and G:. Ask the project where it lives.
$data = if ($env:EV_AI_DATA) { $env:EV_AI_DATA } else {
    & $py -X utf8 -c "import sys;sys.path.insert(0,r'F:\pcap_downloads\ev_charger_ai');from core.paths import DATA_ROOT;print(DATA_ROOT)"
}
$logs = Join-Path $data "logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$driverLog = Join-Path $logs "driver.log"
Set-Location $root

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    # A reader that keeps the log open (Git Bash `tail -F`, an editor) makes
    # Add-Content throw a sharing violation, and with ErrorActionPreference
    # Stop that killed a whole run on 2026-09-15 right after extract_pass1.
    # A log line must never abort the pipeline: retry, then give up quietly.
    for ($i = 0; $i -lt 60; $i++) {
        try { Add-Content -Path $driverLog -Value $line -Encoding UTF8; return }
        catch { Start-Sleep -Milliseconds 500 }
    }
    Write-Warning "driver.log locked for 30 s, line dropped: $line"
}

$stages = @(
    @{ name = "extract_pass1"; args = @("pipeline\extract_all.py", "--workers", "$ExtractWorkers") },
    @{ name = "extract_pass2"; args = @("pipeline\extract_all.py", "--workers", "$ExtractWorkers") },
    @{ name = "sessionize";    args = @("pipeline\sessionize.py", "--workers", "$SessionizeWorkers") },
    @{ name = "split";         args = @("train\make_split.py") },
    @{ name = "dataset";       args = @("train\build_dataset.py", "--workers", "$DatasetWorkers") },
    @{ name = "train_traditional"; args = @("train\train_traditional.py") },
    @{ name = "train_nn_tools";    args = @("train\train_nn_tools.py") },
    @{ name = "train_rl";          args = @("train\train_rl.py") },
    @{ name = "benchmark";     args = @("benchmark\run_competition.py", "test", "0", "$BenchWorkers") },
    @{ name = "analyze";       args = @("benchmark\analyze.py", "test") }
)

$started = ($From -eq "")
$t0 = Get-Date
Log "=== full-fleet run start (From='$From' Force=$Force) data=$data ==="
foreach ($s in $stages) {
    $name = $s.name
    if (-not $started) {
        if ($name -eq $From) { $started = $true } else { Log "skip (before -From): $name"; continue }
    }
    $done = Join-Path $logs "$name.done"
    $failed = Join-Path $logs "$name.failed"
    if ((Test-Path $done) -and -not $Force -and ($From -eq "" -or $name -ne $From)) {
        Log "skip (done): $name"; continue
    }
    Remove-Item $failed -ErrorAction SilentlyContinue
    $log = Join-Path $logs "$name.log"
    $errlog = Join-Path $logs "$name.err.log"
    $argList = @('-X', 'utf8') + $s.args
    $ts = Get-Date
    # Every stage is resumable, so a stage killed by transient pressure on
    # this shared machine is retried rather than aborting the whole run.
    $rc = 1
    for ($try = 1; $try -le 3 -and $rc -ne 0; $try++) {
        if ($try -gt 1) {
            Log "--- RETRY $name (attempt $try) after 120 s"
            Start-Sleep -Seconds 120
            $log = Join-Path $logs "$name.try$try.log"
            $errlog = Join-Path $logs "$name.try$try.err.log"
        }
        Log "--- START $name : python $($s.args -join ' ')"
        # Start-Process rather than a pipeline: piping through Tee-Object
        # waits for stdout EOF, and a pool worker that outlives its parent
        # keeps that pipe open forever, hanging the driver on a stage that
        # already died. Waiting on the process itself cannot hang that way.
        $proc = Start-Process -FilePath $py -ArgumentList $argList `
            -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $log -RedirectStandardError $errlog
        $rc = $proc.ExitCode
    }
    $mins = [math]::Round(((Get-Date) - $ts).TotalMinutes, 1)
    if ($rc -ne 0) {
        $tail = if (Test-Path $errlog) { (Get-Content $errlog -Tail 3) -join ' | ' } else { '' }
        Log "!!! FAILED $name rc=$rc after $mins min - see $log ; stderr: $tail"
        Set-Content -Path $failed -Value "rc=$rc at $(Get-Date)" -Encoding UTF8
        Log "=== run aborted after $([math]::Round(((Get-Date)-$t0).TotalHours,2)) h ==="
        exit $rc
    }
    Set-Content -Path $done -Value "ok at $(Get-Date) ($mins min)" -Encoding UTF8
    Log "--- DONE  $name in $mins min"
}
Log "=== full-fleet run COMPLETE in $([math]::Round(((Get-Date)-$t0).TotalHours,2)) h ==="
