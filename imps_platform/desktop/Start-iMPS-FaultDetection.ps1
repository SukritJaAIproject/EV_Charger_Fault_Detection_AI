#requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$NoOpen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ApiPort = 18765
$AppUrl = "http://localhost:3001/dashboard/ai/fault-detection?desktop=1"
$ApiHealthUrl = "http://localhost:$ApiPort/health"
$DataRootCandidates = @(
    "G:\ev_charger_ai_data_v4",
    "G:\ev_charger_ai_data",
    "E:\ev_charger_ai_data"
)
$DataRoot = $DataRootCandidates |
    Where-Object { Test-Path -LiteralPath (Join-Path $_ "results\records_test.json") -PathType Leaf } |
    Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    throw "Fault-detection benchmark data was not found on the configured local drives."
}
$RuntimeRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "iMPS-FaultDetection"
$LogRoot = Join-Path $RuntimeRoot "logs"
$LauncherLog = Join-Path $LogRoot "launcher.log"
$StatePath = Join-Path $RuntimeRoot "state.json"

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

function Write-LauncherLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Message
    Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
}

function Show-LauncherError {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-LauncherLog "ERROR $Message"
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "$Message`r`n`r`nLog: $LauncherLog",
            "iMPS Fault Detection",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    catch {
        # The launcher also records every failure in launcher.log.
    }
}

function Get-PortProcessChain {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listeners = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Sort-Object OwningProcess -Unique
    )
    $rows = @()
    foreach ($listener in $listeners) {
        $currentId = [int]$listener.OwningProcess
        $depth = 0
        while ($currentId -gt 0 -and $depth -lt 6) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $currentId" -ErrorAction SilentlyContinue
            if ($null -eq $process) { break }
            $rows += [pscustomobject]@{
                Depth = $depth
                PID = [int]$process.ProcessId
                PPID = [int]$process.ParentProcessId
                Name = [string]$process.Name
                CommandLine = [string]$process.CommandLine
            }
            $currentId = [int]$process.ParentProcessId
            $depth++
        }
    }
    return @($rows)
}

function Write-ProcessChain {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][array]$Chain
    )
    foreach ($row in $Chain) {
        Write-LauncherLog (
            "port={0} depth={1} PID={2} PPID={3} name={4} cmd={5}" -f
            $Port, $row.Depth, $row.PID, $row.PPID, $row.Name, $row.CommandLine
        )
    }
}

function Invoke-HttpProbe {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 3
    )
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return [pscustomobject]@{
            Reachable = $true
            Status = [int]$response.StatusCode
            Headers = $response.Headers
            Content = [string]$response.Content
        }
    }
    catch {
        $webResponse = $_.Exception.Response
        if ($null -ne $webResponse) {
            return [pscustomobject]@{
                Reachable = $true
                Status = [int]$webResponse.StatusCode
                Headers = $webResponse.Headers
                Content = ""
            }
        }
        return [pscustomobject]@{
            Reachable = $false
            Status = 0
            Headers = @{}
            Content = ""
        }
    }
}

function Test-DesktopApiReady {
    $probe = Invoke-HttpProbe -Url $ApiHealthUrl
    if (-not $probe.Reachable -or $probe.Status -ne 200) { return $false }
    $marker = $probe.Headers["X-iMPS-Desktop-Service"]
    if ($marker -ne "fault-detection") { return $false }
    try {
        $health = $probe.Content | ConvertFrom-Json
        return $health.status -eq "ok" -and $health.models -eq 5
    }
    catch {
        return $false
    }
}

function Test-FrontendReady {
    $probe = Invoke-HttpProbe -Url $AppUrl -TimeoutSec 5
    return $probe.Reachable -and $probe.Status -eq 200
}

function Wait-Until {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Description
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Description."
}

function Find-CompatiblePython {
    $candidates = @(
        "C:\Python313\python.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )
    try {
        $command = Get-Command python.exe -ErrorAction Stop
        $candidates += [string]$command.Source
    }
    catch {
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import fastapi" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    throw "A Python installation with FastAPI was not found."
}

function Assert-ExpectedResults {
    $required = @(
        (Join-Path $DataRoot "results\leaderboard_test.json"),
        (Join-Path $DataRoot "results\analysis_test.json"),
        (Join-Path $DataRoot "results\records_test.json"),
        (Join-Path $DataRoot "split.json")
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required full-fleet result is missing: $path"
        }
        if ((Get-Item -LiteralPath $path).Length -le 0) {
            throw "Required full-fleet result is empty: $path"
        }
    }
}

function Ensure-FaultDetectionApi {
    $chain = @(Get-PortProcessChain -Port $ApiPort)
    if ($chain.Count -gt 0) {
        Write-ProcessChain -Port $ApiPort -Chain $chain
        if (Test-DesktopApiReady) {
            Write-LauncherLog "Reusing the verified desktop results API on port $ApiPort."
            return $null
        }
        throw "Port $ApiPort is already used by an unrecognized process. No process was stopped."
    }

    $python = Find-CompatiblePython
    $apiScript = Join-Path $PSScriptRoot "fault_detection_api.py"
    $stdoutPath = Join-Path $LogRoot "results-api.stdout.log"
    $stderrPath = Join-Path $LogRoot "results-api.stderr.log"
    $arguments = @(
        "-u",
        ('"{0}"' -f $apiScript),
        "--host", "127.0.0.1",
        "--port", [string]$ApiPort,
        "--data-root", ('"{0}"' -f $DataRoot)
    )
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -WindowStyle Hidden -PassThru
    Write-LauncherLog "Started desktop results API PID=$($process.Id) PPID=$PID python=$python"
    Wait-Until -Condition { Test-DesktopApiReady } -TimeoutSeconds 20 -Description "the results API"
    Write-LauncherLog "Desktop results API is ready on port $ApiPort."
    return [int]$process.Id
}

function Ensure-Frontend {
    $chain = @(Get-PortProcessChain -Port 3001)
    if ($chain.Count -gt 0) {
        Write-ProcessChain -Port 3001 -Chain $chain
        $commands = ($chain | ForEach-Object { $_.CommandLine }) -join "`n"
        $isProjectFrontend = $commands.Contains($ProjectRoot) -and $commands -match "(?i)next"
        if ($isProjectFrontend -and (Test-FrontendReady)) {
            Write-LauncherLog "Reusing the verified iMPS frontend on port 3001."
            return $null
        }
        throw "Port 3001 is already used by an unrecognized or unhealthy process. No process was stopped."
    }

    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "node_modules\next\package.json"))) {
        throw "Frontend dependencies are missing. Run npm install --legacy-peer-deps first."
    }
    $stdoutPath = Join-Path $LogRoot "frontend.stdout.log"
    $stderrPath = Join-Path $LogRoot "frontend.stderr.log"
    $process = Start-Process -FilePath $npm -ArgumentList @("run", "dev") -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -WindowStyle Hidden -PassThru
    Write-LauncherLog "Started iMPS frontend starter PID=$($process.Id) PPID=$PID npm=$npm"
    Wait-Until -Condition { Test-FrontendReady } -TimeoutSeconds 55 -Description "the iMPS frontend"
    Write-LauncherLog "iMPS frontend is ready on port 3001."
    return [int]$process.Id
}

function Open-FaultDetectionApp {
    $edgeCandidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        (Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe")
    )
    $edge = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ($null -ne $edge) {
        Start-Process -FilePath $edge -ArgumentList @("--app=$AppUrl", "--start-maximized") | Out-Null
        Write-LauncherLog "Opened Edge app window: $AppUrl"
        return
    }
    Start-Process $AppUrl | Out-Null
    Write-LauncherLog "Microsoft Edge was not found; opened the default browser: $AppUrl"
}

$mutex = New-Object System.Threading.Mutex($false, "Local\iMPSFaultDetectionLauncher")
$hasMutex = $false
try {
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) {
        Write-LauncherLog "Another launcher instance is already starting the app; this click exits."
        exit 0
    }

    Write-LauncherLog "Launcher started. project=$ProjectRoot"
    Assert-ExpectedResults
    $apiPid = Ensure-FaultDetectionApi
    $frontendPid = Ensure-Frontend
    [pscustomobject]@{
        updatedAt = (Get-Date).ToString("o")
        projectRoot = $ProjectRoot
        url = $AppUrl
        apiStartedPid = $apiPid
        frontendStartedPid = $frontendPid
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

    if (-not $NoOpen) {
        Open-FaultDetectionApp
    }
    Write-LauncherLog "Launcher completed successfully."
}
catch {
    Show-LauncherError -Message $_.Exception.Message
    exit 1
}
finally {
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
