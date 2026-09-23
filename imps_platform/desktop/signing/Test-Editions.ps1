# Install several iMPS Fault Detection editions side by side into sandboxes, prove Windows
# sees them as separate applications, run them all at once, check what each reports on
# /health, then uninstall everything. Exit code 1 on any failed check.
#
#   -Edition 'label|installer.exe|Main Exe.exe|expectedArtifact|expectedProduct|expectedVersion|expectedPolicy'
param(
    [Parameter(Mandatory = $true)][string[]]$Edition,
    [string]$Sandbox = 'C:\ev_fleet\editions_smoke'
)
$ErrorActionPreference = 'Continue'
$fail = 0
function Check($ok, $msg) { if ($ok) { "PASS  $msg" } else { "FAIL  $msg"; $script:fail++ } }
function Warn($msg) { "WARN  $msg" }
function UninstallEntries { Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DisplayName -like 'iMPS Fault Detection*' } }
function Desc($all, $p) { foreach ($k in ($all | Where-Object { $_.ParentProcessId -eq $p })) { $k; Desc $all $k.ProcessId } }
function StopTree($pid0) { $all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId; foreach ($x in ((@(Desc $all $pid0) + @($all | Where-Object ProcessId -eq $pid0)) | Sort-Object ProcessId -Descending)) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue } }

$eds = foreach ($e in $Edition) {
    $label, $installer, $exe, $artifact, $product, $version, $policy = $e -split '\|'
    [pscustomobject]@{ label = $label; installer = $installer; exe = $exe; artifact = $artifact; product = $product; version = $version; policy = $policy; dir = Join-Path $Sandbox $label }
}
if ([IO.Directory]::Exists($Sandbox)) { [IO.Directory]::Delete($Sandbox, $true) }
[IO.Directory]::CreateDirectory($Sandbox) | Out-Null
# The installers create a Desktop shortcut named after the product and the uninstallers delete
# it, which takes the user's own shortcut of the same name with it; keep copies and put them back.
$desk = [Environment]::GetFolderPath('Desktop')
$lnkBackup = Join-Path $env:TEMP ('imps_desktop_lnk_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
[IO.Directory]::CreateDirectory($lnkBackup) | Out-Null
$savedLinks = @(Get-ChildItem $desk -Filter 'iMPS*.lnk' -File)
foreach ($l in $savedLinks) { Copy-Item -LiteralPath $l.FullName -Destination $lnkBackup }
$silent = '/' + 'S'
Check ((UninstallEntries | Measure-Object).Count -eq 0) "no iMPS uninstall entries before the test"

foreach ($e in $eds) {
    $p = Start-Process -FilePath $e.installer -ArgumentList @($silent, ('/' + "D=$($e.dir)")) -PassThru -Wait
    Check ($p.ExitCode -eq 0) "$($e.label): silent install exit $($p.ExitCode)"
}
$entries = @(UninstallEntries)
Check ($entries.Count -eq $eds.Count) "$($eds.Count) uninstall entries: $(($entries.DisplayName) -join ' | ')"
Check ((@($eds | ForEach-Object { $_.exe }) | Sort-Object -Unique).Count -eq $eds.Count) "distinct executables"
foreach ($e in $eds) {
    $main = Join-Path $e.dir $e.exe
    $s = Get-AuthenticodeSignature $main
    Check ($s.SignerCertificate.Thumbprint -eq '74C4795C67E81EFCCFFAAB2B946661F1003C7A3E') "$($e.label): $($e.exe) signed with the internal certificate"
    $ws = Get-AuthenticodeSignature (Join-Path $e.dir 'resources\runtime\wireshark\tshark.exe')
    Check ($ws.Status -eq 'Valid' -and $ws.SignerCertificate.Subject -like '*Wireshark Foundation*') "$($e.label): tshark.exe keeps the Wireshark Foundation signature"
    $art = (Get-Content (Join-Path $e.dir 'resources\models\manifest.json') -Raw | ConvertFrom-Json).artifactVersion
    Check ($art -eq $e.artifact) "$($e.label): model artifact $art"
}

# all editions running at once, each reporting its own identity and policy
$runs = @()
foreach ($e in $eds) { $runs += [pscustomobject]@{ e = $e; p = (Start-Process -FilePath (Join-Path $e.dir $e.exe) -WorkingDirectory $e.dir -PassThru) } }
$deadline = (Get-Date).AddSeconds(300)
foreach ($r in $runs) {
    $health = $null
    while (-not $health -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        foreach ($side in (Get-CimInstance Win32_Process -Filter "Name='imps-fault-runtime.exe'")) {
            if ($side.ParentProcessId -eq $r.p.Id -and $side.CommandLine -match '--port\s+(\d+)') {
                try { $health = (Invoke-WebRequest -Uri "http://127.0.0.1:$($matches[1])/health" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json } catch {}
            }
        }
    }
    $policy = if ($health.detectionPolicy) { $health.detectionPolicy.id } else { '' }
    Check ($health -and $health.status -eq 'ok' -and $health.productName -eq $r.e.product -and $health.appVersion -eq $r.e.version -and $health.artifactVersion -eq $r.e.artifact -and $policy -eq $r.e.policy) "$($r.e.label): /health $($health.productName) v$($health.appVersion) model $($health.artifactVersion) policy $policy status $($health.status)"
}
$appdata = @(Get-ChildItem $env:APPDATA -Directory | Where-Object { $_.Name -like 'iMPS Fault Detection*' } | Select-Object -ExpandProperty Name)
Check (@($eds | Where-Object { $appdata -notcontains $_.product }).Count -eq 0) "separate %APPDATA% folders: $($appdata -join ' | ')"
foreach ($r in $runs) { StopTree $r.p.Id }
Start-Sleep -Seconds 10

# The window is checked on a second, warm start. On this machine endpoint protection scans
# freshly installed binaries on their first launch, which can hold the renderer back for
# minutes (2026-09-23: never within 9 min cold, 8 s warm); /health above covers the cold start.
$runs = @()
foreach ($e in $eds) { $runs += [pscustomobject]@{ e = $e; p = (Start-Process -FilePath (Join-Path $e.dir $e.exe) -WorkingDirectory $e.dir -PassThru) } }
foreach ($r in $runs) {
    $d2 = (Get-Date).AddSeconds(120); $t0 = Get-Date
    do { Start-Sleep -Seconds 2; $r.p.Refresh() } while ((Get-Date) -lt $d2 -and $r.p.MainWindowTitle -ne $r.e.product)
    Check ($r.p.MainWindowTitle -eq $r.e.product) ("{0}: window title '{1}' on warm start ({2:n0}s)" -f $r.e.label, $r.p.MainWindowTitle, ((Get-Date) - $t0).TotalSeconds)
}
foreach ($r in $runs) { StopTree $r.p.Id }
Start-Sleep -Seconds 10

foreach ($e in $eds) {
    $un = Get-ChildItem $e.dir -Filter 'Uninstall*.exe' | Select-Object -First 1
    $p = Start-Process -FilePath $un.FullName -ArgumentList @($silent) -PassThru -Wait
    Check ($p.ExitCode -eq 0) "$($e.label): uninstall exit $($p.ExitCode)"
}
Start-Sleep -Seconds 8
Check ((UninstallEntries | Measure-Object).Count -eq 0) "no uninstall entries left"
$left = @(Get-ChildItem $Sandbox -Recurse -File -ErrorAction SilentlyContinue)
if ($left.Count) { Warn "$($left.Count) file(s) left (endpoint security may still hold them): $(($left | Select-Object -First 5 | ForEach-Object { $_.Name }) -join ', ')" } else { "PASS  no files left" }
try { [IO.Directory]::Delete($Sandbox, $true) } catch { Warn "sandbox left for later cleanup: $Sandbox" }
foreach ($l in $savedLinks) { Copy-Item -LiteralPath (Join-Path $lnkBackup $l.Name) -Destination $desk -Force }
$lost = @($savedLinks | Where-Object { -not (Test-Path -LiteralPath (Join-Path $desk $_.Name)) })
Check ($lost.Count -eq 0) "user's Desktop shortcuts restored: $(($savedLinks.Name) -join ' | ')"
"`n$fail failure(s)"
exit $(if ($fail) { 1 } else { 0 })
