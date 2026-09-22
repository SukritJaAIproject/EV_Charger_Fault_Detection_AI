[CmdletBinding()]
param(
    [string]$RuntimeExecutable = "",
    [string]$ResourcesRoot = "",
    [string]$GoldenPcap = "G:\pcap_downloads\001_7Eleven_Banklangmueang\connector1\ethlog12.pcap",
    [string]$HealthyPcap = "$env:LOCALAPPDATA\iMPS-FaultDetection\jobs\desktop\396e751d4bf7489cb7917fe1917f169e\input.pcap",
    [switch]$SkipHealthy
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runtimeRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $runtimeRoot "..\.."))
$buildRoot = Join-Path $projectRoot ".desktop-build"
if ([string]::IsNullOrWhiteSpace($ResourcesRoot)) {
    $summary = Join-Path $buildRoot "summary.json"
    $models = Join-Path $buildRoot "models"
    $tshark = Join-Path $buildRoot "runtime\wireshark\tshark.exe"
    if ([string]::IsNullOrWhiteSpace($RuntimeExecutable)) {
        $RuntimeExecutable = Join-Path $buildRoot "runtime\imps-fault-runtime.exe"
    }
}
else {
    $ResourcesRoot = [System.IO.Path]::GetFullPath($ResourcesRoot)
    $summary = Join-Path $ResourcesRoot "data\summary.json"
    $models = Join-Path $ResourcesRoot "models"
    $tshark = Join-Path $ResourcesRoot "runtime\wireshark\tshark.exe"
    if ([string]::IsNullOrWhiteSpace($RuntimeExecutable)) {
        $RuntimeExecutable = Join-Path $ResourcesRoot "runtime\imps-fault-runtime.exe"
    }
}
$RuntimeExecutable = [System.IO.Path]::GetFullPath($RuntimeExecutable)
$smokeRoot = Join-Path $buildRoot "runtime-smoke"
$jobsRoot = Join-Path $smokeRoot "jobs"
$stdout = Join-Path $smokeRoot "server.stdout.log"
$stderr = Join-Path $smokeRoot "server.stderr.log"

foreach ($required in @($RuntimeExecutable, $summary, $models, $tshark, $GoldenPcap)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Smoke-test input is missing: $required"
    }
}
if (-not $SkipHealthy -and -not (Test-Path -LiteralPath $HealthyPcap -PathType Leaf)) {
    throw "Healthy smoke-test PCAP is missing: $HealthyPcap"
}
New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()
$origin = "http://127.0.0.1:3001"
$baseUrl = "http://127.0.0.1:$port"

$arguments = @(
    "serve", "--host", "127.0.0.1", "--port", [string]$port,
    "--origin", $origin,
    "--summary", $summary,
    "--model-dir", $models,
    "--tshark", $tshark,
    "--jobs-root", $jobsRoot
)
$runtimeProcess = Start-Process -FilePath $RuntimeExecutable -ArgumentList $arguments `
    -WorkingDirectory (Split-Path -Parent $RuntimeExecutable) -WindowStyle Hidden `
    -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr

function Wait-UntilReady {
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if ($runtimeProcess.HasExited) {
            throw "Runtime exited before becoming ready (exit $($runtimeProcess.ExitCode))"
        }
        try {
            $health = Invoke-RestMethod -UseBasicParsing -Uri "$baseUrl/health" -TimeoutSec 2
            if ($health.inferenceReady -eq $true) {
                return $health
            }
        }
        catch {
            # A 503 is expected while the deep runtime check is still running.
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Runtime did not become inference-ready"
}

function Invoke-PcapAnalysis {
    param(
        [Parameter(Mandatory = $true)][string]$Pcap,
        [Parameter(Mandatory = $true)][string]$Filename
    )
    $upload = Invoke-WebRequest -UseBasicParsing -Method Post `
        -Uri "$baseUrl/ai/fault-detection/jobs" -InFile $Pcap `
        -ContentType "application/octet-stream" `
        -Headers @{ Origin = $origin; "X-Filename" = $Filename; Accept = "application/json" }
    $job = $upload.Content | ConvertFrom-Json
    for ($attempt = 0; $attempt -lt 600; $attempt++) {
        if ($job.status -notin @("queued", "processing")) {
            break
        }
        Start-Sleep -Milliseconds 500
        $job = Invoke-RestMethod -UseBasicParsing `
            -Uri "$baseUrl/ai/fault-detection/jobs/$($job.jobId)" `
            -Headers @{ Origin = $origin; Accept = "application/json" } -TimeoutSec 5
    }
    if ($job.status -ne "complete") {
        throw "PCAP job failed: status=$($job.status) error=$($job.error)"
    }
    return $job
}

try {
    $health = Wait-UntilReady
    $golden = Invoke-PcapAnalysis -Pcap $GoldenPcap -Filename "ethlog12.pcap"
    if ($golden.result.verdict.status -ne "fault_detected" -or
        $golden.result.verdict.faultFamily -ne "PROTOCOL_FAILED" -or
        $golden.result.capture.extractedEvents -ne 1106 -or
        $golden.result.capture.sessionCount -ne 1) {
        throw "Golden PCAP result did not match the audited baseline"
    }

    $healthy = $null
    if (-not $SkipHealthy) {
        $healthy = Invoke-PcapAnalysis -Pcap $HealthyPcap -Filename "healthy-reference.pcap"
        if ($healthy.result.verdict.status -ne "no_fault_detected" -or
            $healthy.result.capture.extractedEvents -ne 534 -or
            $healthy.result.capture.sessionCount -ne 1) {
            throw "Healthy PCAP result did not match the audited baseline"
        }
    }

    [pscustomobject]@{
        status = "PASS"
        health = $health.status
        artifactVersion = $golden.result.model.artifactVersion
        golden = [ordered]@{
            verdict = $golden.result.verdict.status
            faultFamily = $golden.result.verdict.faultFamily
            events = $golden.result.capture.extractedEvents
            sessions = $golden.result.capture.sessionCount
            durationSeconds = $golden.result.processing.durationSeconds
        }
        healthy = if ($null -eq $healthy) { $null } else { [ordered]@{
            verdict = $healthy.result.verdict.status
            events = $healthy.result.capture.extractedEvents
            sessions = $healthy.result.capture.sessionCount
            durationSeconds = $healthy.result.processing.durationSeconds
        }}
    } | ConvertTo-Json -Depth 6
}
finally {
    if (-not $runtimeProcess.HasExited) {
        Stop-Process -Id $runtimeProcess.Id -Force
        $runtimeProcess.WaitForExit()
    }
    if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout }
    if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr }
}
