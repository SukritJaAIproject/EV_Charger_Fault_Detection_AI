# Install the current line (1.2.0) and the Snapshot edition (1.1.0) side by side
# into two sandboxes, prove they are two distinct Windows applications (two
# uninstall entries, two %APPDATA% folders), start both headless, then remove
# both and leave the machine as it was. Exit code 1 on any failed check.
param(
    [string]$Current = 'C:\Users\user1\Documents\GitHub\IMPS-Project\iMPS_platform\dist-desktop\release-gh-v1.2.1\iMPS-Fault-Detection-Offline-Setup-1.2.1.exe',
    [string]$Snapshot = 'C:\Users\user1\Documents\GitHub\IMPS-Project\iMPS_platform\dist-desktop\release-gh-snapshot-v1.1.1\iMPS-Fault-Detection-Snapshot-2026-09-12-Offline-Setup-1.1.1.exe',
    [string]$Sandbox = 'C:\ev_fleet\coexist_smoke'
)
$ErrorActionPreference = 'Continue'
$fail = 0
function Check($ok, $msg) { if ($ok) { "PASS  $msg" } else { "FAIL  $msg"; $script:fail++ } }
function Warn($msg) { "WARN  $msg" }
function UninstallEntries { Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DisplayName -like 'iMPS Fault Detection*' } }

# Who holds a file open or mapped, from the Windows Restart Manager. Endpoint
# security (Cortex XDR on EGAT machines, Defender elsewhere) analyses a freshly
# executed executable while holding it, and an uninstaller that runs meanwhile
# leaves that file behind (NSIS Delete gives up on a held file). That is not a
# product defect, so the checks below wait for the release and downgrade a
# leftover that is still held by another process to a warning.
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class RmWho {
    [StructLayout(LayoutKind.Sequential)] struct RM_UNIQUE_PROCESS { public int dwProcessId; public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct RM_PROCESS_INFO {
        public RM_UNIQUE_PROCESS Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string strAppName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string strServiceShortName;
        public int ApplicationType; public uint AppStatus; public uint TSSessionId; [MarshalAs(UnmanagedType.Bool)] public bool bRestartable; }
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] static extern int RmStartSession(out uint pSessionHandle, int dwSessionFlags, string strSessionKey);
    [DllImport("rstrtmgr.dll")] static extern int RmEndSession(uint pSessionHandle);
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)] static extern int RmRegisterResources(uint pSessionHandle, uint nFiles, string[] rgsFilenames, uint nApplications, IntPtr rgApplications, uint nServices, string[] rgsServiceNames);
    [DllImport("rstrtmgr.dll")] static extern int RmGetList(uint dwSessionHandle, out uint pnProcInfoNeeded, ref uint pnProcInfo, [In, Out] RM_PROCESS_INFO[] rgAffectedApps, ref uint lpdwRebootReasons);
    public static List<string> Holders(string path) {
        var result = new List<string>(); uint handle; string key = Guid.NewGuid().ToString();
        if (RmStartSession(out handle, 0, key) != 0) throw new Exception("RmStartSession failed");
        try {
            if (RmRegisterResources(handle, 1, new[] { path }, 0, IntPtr.Zero, 0, null) != 0) throw new Exception("RmRegisterResources failed");
            uint needed = 0, count = 0, reasons = 0;
            int rc = RmGetList(handle, out needed, ref count, null, ref reasons);
            if (rc == 234) { var arr = new RM_PROCESS_INFO[needed]; count = needed; rc = RmGetList(handle, out needed, ref count, arr, ref reasons);
                if (rc == 0) for (int i = 0; i < count; i++) result.Add(arr[i].strAppName + " (pid " + arr[i].Process.dwProcessId + ")"); }
            else if (rc != 0) throw new Exception("RmGetList rc=" + rc);
        } finally { RmEndSession(handle); }
        return result;
    }
}
'@
function FileHolders($file) { try { @([RmWho]::Holders($file)) } catch { @() } }
function WaitForRelease($file, $timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    do {
        $h = FileHolders $file
        if ($h.Count -eq 0) { return $true }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)
    "      still held by: " + ($h -join ', ')
    return $false
}
function WaitForSandboxProcesses($root, $timeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    do {
        $running = @(Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) })
        if ($running.Count -eq 0) { return $true }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    "      still running: " + (($running | ForEach-Object { "$($_.ProcessName) ($($_.Id))" }) -join ', ')
    return $false
}

if ([IO.Directory]::Exists($Sandbox)) { [IO.Directory]::Delete($Sandbox, $true) }
[IO.Directory]::CreateDirectory($Sandbox) | Out-Null
$silent = '/' + 'S'
Check ((UninstallEntries | Measure-Object).Count -eq 0) "no iMPS uninstall entries before the test"

foreach ($e in @(@{ name = 'current'; exe = $Current; dir = "$Sandbox\current" }, @{ name = 'snapshot'; exe = $Snapshot; dir = "$Sandbox\snapshot" })) {
    $p = Start-Process -FilePath $e.exe -ArgumentList @($silent, ('/' + "D=$($e.dir)")) -PassThru -Wait
    Check ($p.ExitCode -eq 0) "$($e.name): silent install exit $($p.ExitCode)"
}
$entries = UninstallEntries
Check ($entries.Count -eq 2) "two uninstall entries present: $(($entries.DisplayName) -join ' | ')"
$curExe = Get-ChildItem "$Sandbox\current" -Filter '*.exe' | Where-Object { $_.Name -notlike 'Uninstall*' } | Select-Object -First 1
$snapExe = Get-ChildItem "$Sandbox\snapshot" -Filter '*.exe' | Where-Object { $_.Name -notlike 'Uninstall*' } | Select-Object -First 1
Check ($curExe -and $snapExe -and $curExe.Name -ne $snapExe.Name) "distinct executables: '$($curExe.Name)' vs '$($snapExe.Name)'"
foreach ($x in @($curExe, $snapExe)) { $s = Get-AuthenticodeSignature $x.FullName; Check ($s.SignerCertificate.Thumbprint -eq '74C4795C67E81EFCCFFAAB2B946661F1003C7A3E') "$($x.Name) signed with the internal certificate ($($s.Status))" }
foreach ($d in @("$Sandbox\current", "$Sandbox\snapshot")) {
    $ws = Get-AuthenticodeSignature "$d\resources\runtime\wireshark\tshark.exe"
    Check ($ws.Status -eq 'Valid' -and $ws.SignerCertificate.Subject -like '*Wireshark Foundation*') "$(Split-Path $d -Leaf): bundled tshark.exe still signed by Wireshark Foundation ($($ws.Status))"
}
$curArt = (Get-Content "$Sandbox\current\resources\models\manifest.json" -Raw | ConvertFrom-Json).artifactVersion
$snapArt = (Get-Content "$Sandbox\snapshot\resources\models\manifest.json" -Raw | ConvertFrom-Json).artifactVersion
Check ($curArt -eq '53b6f14244c2e633' -and $snapArt -eq '41ded2cdd5c2ba3f') "model artifacts: current=$curArt snapshot=$snapArt"
$curSnap = (Get-Content "$Sandbox\current\resources\data\summary.json" -Raw | ConvertFrom-Json).snapshotAt
$snapSnap = (Get-Content "$Sandbox\snapshot\resources\data\summary.json" -Raw | ConvertFrom-Json).snapshotAt
Check ($curSnap -like '2026-09-21*' -and $snapSnap -like '2026-09-12*') "data snapshots: current=$curSnap snapshot=$snapSnap"

# both editions running at the same time, each with its own %APPDATA% folder
$procs = @()
foreach ($x in @($curExe, $snapExe)) { $procs += Start-Process -FilePath $x.FullName -ArgumentList '--smoke-test' -PassThru }
foreach ($pr in $procs) { $pr.WaitForExit(240000) | Out-Null; Check ($pr.ExitCode -eq 0) "$($pr.StartInfo.FileName | Split-Path -Leaf) --smoke-test (concurrently) exit $($pr.ExitCode)" }
$appdata = Get-ChildItem $env:APPDATA -Directory | Where-Object { $_.Name -like 'iMPS Fault Detection*' } | Select-Object -ExpandProperty Name
Check (($appdata -contains 'iMPS Fault Detection') -and ($appdata -contains 'iMPS Fault Detection Snapshot 2026-09-12')) "separate %APPDATA% folders: $($appdata -join ' | ')"
Check (WaitForSandboxProcesses $Sandbox 60) "no process from either install still running before uninstall"
foreach ($x in @($curExe, $snapExe)) {
    if (WaitForRelease $x.FullName 300) { "PASS  $($x.Name) not held by any other process before uninstall" }
    else { Warn "$($x.Name) is still held by another process (endpoint security scan); uninstalling anyway" }
}

foreach ($d in @("$Sandbox\current", "$Sandbox\snapshot")) {
    $un = Get-ChildItem $d -Filter 'Uninstall*.exe' | Select-Object -First 1
    $p = Start-Process -FilePath $un.FullName -ArgumentList @($silent) -PassThru -Wait
    Check ($p.ExitCode -eq 0) "uninstall $($un.Name) exit $($p.ExitCode)"
}
# the NSIS uninstaller deletes its own copy after it exits
$null = WaitForSandboxProcesses $Sandbox 30
Start-Sleep -Seconds 5
Check ((UninstallEntries | Measure-Object).Count -eq 0) "no uninstall entries left"
$left = @(Get-ChildItem $Sandbox -Recurse -File -ErrorAction SilentlyContinue)
if ($left.Count -eq 0) { "PASS  no files left in sandboxes" }
else {
    $unexplained = @()
    foreach ($f in $left) {
        $h = FileHolders $f.FullName
        $rel = $f.FullName.Substring($Sandbox.Length + 1)
        if ($h.Count) { Warn "left behind while held by $($h -join ', '): $rel" } else { $unexplained += $rel }
    }
    Check ($unexplained.Count -eq 0) "no unexplained files left in sandboxes$(if ($unexplained.Count) { ': ' + ($unexplained -join ', ') })"
}
if ([IO.Directory]::Exists($Sandbox)) { try { [IO.Directory]::Delete($Sandbox, $true) } catch { Warn "sandbox $Sandbox could not be removed yet: $($_.Exception.Message)" } }
"`n$fail failure(s)"
exit $(if ($fail) { 1 } else { 0 })
